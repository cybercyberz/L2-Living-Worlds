/*
 * Copyright (c) 2013 L2jMobius
 *
 * Permission is hereby granted, free of charge, to any person obtaining a copy
 * of this software and associated documentation files (the "Software"), to deal
 * in the Software without restriction, including without limitation the rights
 * to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
 * copies of the Software, and to permit persons to whom the Software is
 * furnished to do so, subject to the following conditions:
 *
 * The above copyright notice and this permission notice shall be
 * included in all copies or substantial portions of the Software.
 *
 * THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
 * IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
 * FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
 * AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY,
 * WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR
 * IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.
 */
package modules.phantomcombat;

import java.lang.reflect.Field;
import java.util.ArrayDeque;
import java.util.ArrayList;
import java.util.Collection;
import java.util.Deque;
import java.util.Iterator;
import java.util.List;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;

import org.l2jmobius.gameserver.config.custom.ClassBalanceConfig;
import org.l2jmobius.gameserver.model.WorldObject;
import org.l2jmobius.gameserver.model.actor.Creature;
import org.l2jmobius.gameserver.model.actor.Player;
import org.l2jmobius.gameserver.model.effects.AbstractEffect;
import org.l2jmobius.gameserver.model.groups.Party;
import org.l2jmobius.gameserver.model.item.enums.ShotType;
import org.l2jmobius.gameserver.model.skill.EffectScope;
import org.l2jmobius.gameserver.model.skill.Skill;
import org.l2jmobius.gameserver.model.stats.Formulas;
import org.l2jmobius.gameserver.model.stats.Stat;

/**
 * What every healer knows about the party: each member's HP, the damage it is taking, and what every caster (phantom
 * or human) is already doing about it.
 * <p>
 * The <b>intent ledger</b> holds one entry per cast on its way: a single heal, a share of a group heal, a cleanse or a
 * recharge, with its estimated amount and landing time. It is filled from the skill-use event, so a heal the human
 * leader starts counts exactly like a phantom's. An entry lives only while its caster is still casting that skill and
 * the landing time is ahead; an aborted or finished cast drops out on its own. Resurrections are held longer, until
 * the corpse stands up, because the revive request lands after the cast.
 * <p>
 * The heal estimate follows {@code handlers.skill.effects.Heal}: power + spiritshot bonus + sqrt(mAtkMul x mAtk), times
 * the target's heal-effect stat and the class healing multiplier. {@code HealPercent} is a share of max HP.
 */
final class PartyBoard
{
	enum Kind
	{
		HEAL, // single-target heal
		GROUP, // one member's share of a party heal
		CLEANSE,
		RECHARGE
	}

	static final class Intent
	{
		final Kind kind;
		final Player caster;
		final int skillId;
		final Creature target;
		final int targetId;
		final double amount;
		final long landAt;

		Intent(Kind kind, Player caster, int skillId, Creature target, double amount, long landAt)
		{
			this.kind = kind;
			this.caster = caster;
			this.skillId = skillId;
			this.target = target;
			this.targetId = target.getObjectId();
			this.amount = amount;
			this.landAt = landAt;
		}

		/** Still on its way: the caster is casting this skill and the landing time is ahead. */
		boolean alive(long now)
		{
			return (now < landAt) && !caster.isDead() && caster.isCastingNow() && (caster.getLastSkillCast() != null) && (caster.getLastSkillCast().getId() == skillId);
		}
	}

	/** Damage taken is averaged over this window. */
	private static final long DAMAGE_WINDOW_MS = 3000;
	/** A resurrection claim is held until the corpse stands, but never longer than this. */
	private static final long RES_CLAIM_CAP_MS = 12000;
	/** How long one party-wide emergency skill (Benediction, Balance Life) blocks the others. */
	private static final long EMERGENCY_CLAIM_MS = 10000;

	private final List<Intent> _intents = new ArrayList<>();
	/** corpse object id -> {caster object id, until}. */
	private final Map<Integer, long[]> _resClaims = new ConcurrentHashMap<>();
	/** party leader object id -> until. */
	private final Map<Integer, Long> _emergencyClaims = new ConcurrentHashMap<>();
	/** player object id -> recent {time, damage} hits. */
	private final Map<Integer, Deque<long[]>> _damage = new ConcurrentHashMap<>();
	/** Effect class -> its private power field (read once per class). */
	private final Map<Class<?>, Field> _powerFields = new ConcurrentHashMap<>();

	// ===== Damage in =====

	void onDamaged(Player target, double damage, long now)
	{
		final Deque<long[]> hits = _damage.computeIfAbsent(target.getObjectId(), k -> new ArrayDeque<>());
		synchronized (hits)
		{
			hits.addLast(new long[]
			{
				now,
				(long) damage
			});
			while (!hits.isEmpty() && ((now - hits.peekFirst()[0]) > DAMAGE_WINDOW_MS))
			{
				hits.removeFirst();
			}
		}
	}

	/** Damage per second {@code who} took over the last few seconds. */
	double dtps(Creature who, long now)
	{
		final Deque<long[]> hits = _damage.get(who.getObjectId());
		if (hits == null)
		{
			return 0;
		}
		long sum = 0;
		synchronized (hits)
		{
			for (long[] hit : hits)
			{
				if ((now - hit[0]) <= DAMAGE_WINDOW_MS)
				{
					sum += hit[1];
				}
			}
		}
		return sum / (DAMAGE_WINDOW_MS / 1000.0);
	}

	// ===== The ledger =====

	/** Records what a cast that is starting will do. Called from the skill-use event for every player caster. */
	void record(Player caster, Skill skill, Creature target, Collection<WorldObject> targets, long now)
	{
		final long landAt = now + castTime(caster, skill);
		final boolean party = isPartySkill(skill);
		for (AbstractEffect effect : skill.getEffects(EffectScope.GENERAL))
		{
			switch (effect.getClass().getSimpleName())
			{
				case "Heal":
				case "HealPercent":
				{
					if (party)
					{
						if (targets != null)
						{
							for (WorldObject object : targets)
							{
								if (object instanceof Creature)
								{
									add(new Intent(Kind.GROUP, caster, skill.getId(), (Creature) object, estimate(caster, skill, (Creature) object), landAt));
								}
							}
						}
					}
					else if (target != null)
					{
						add(new Intent(Kind.HEAL, caster, skill.getId(), target, estimate(caster, skill, target), landAt));
					}
					break;
				}
				case "DispelBySlot":
				case "DispelByCategory":
				{
					if ((target != null) && !party)
					{
						add(new Intent(Kind.CLEANSE, caster, skill.getId(), target, 0, landAt));
					}
					break;
				}
				case "ManaHealByLevel":
				{
					if ((target != null) && !party)
					{
						add(new Intent(Kind.RECHARGE, caster, skill.getId(), target, 0, landAt));
					}
					break;
				}
				case "Resurrection":
				{
					if ((target != null) && target.isDead())
					{
						claimRes(caster, target, landAt - now);
					}
					break;
				}
			}
		}
	}

	private void add(Intent intent)
	{
		synchronized (_intents)
		{
			// One entry per caster, kind and target: a recast replaces the old one.
			_intents.removeIf(i -> (i.caster == intent.caster) && (i.kind == intent.kind) && (i.targetId == intent.targetId));
			_intents.add(intent);
		}
	}

	/** Drops finished and aborted casts, and resurrection claims whose corpse is up or whose time ran out. */
	void sweep(long now)
	{
		synchronized (_intents)
		{
			_intents.removeIf(i -> !i.alive(now));
		}
		for (Iterator<Map.Entry<Integer, long[]>> it = _resClaims.entrySet().iterator(); it.hasNext();)
		{
			if (it.next().getValue()[1] <= now)
			{
				it.remove();
			}
		}
		_emergencyClaims.values().removeIf(until -> until <= now);
		for (Iterator<Deque<long[]>> it = _damage.values().iterator(); it.hasNext();)
		{
			final Deque<long[]> hits = it.next();
			synchronized (hits)
			{
				while (!hits.isEmpty() && ((now - hits.peekFirst()[0]) > DAMAGE_WINDOW_MS))
				{
					hits.removeFirst();
				}
				if (hits.isEmpty())
				{
					it.remove();
				}
			}
		}
	}

	/** HP already on its way to {@code who} from casts by anyone other than {@code except}. */
	double incoming(Creature who, Player except, long now)
	{
		double sum = 0;
		synchronized (_intents)
		{
			for (Intent i : _intents)
			{
				if ((i.targetId == who.getObjectId()) && ((i.kind == Kind.HEAL) || (i.kind == Kind.GROUP)) && (i.caster != except) && i.alive(now))
				{
					sum += i.amount;
				}
			}
		}
		return sum;
	}

	/** The HP {@code who} still misses once everything on its way has landed (never negative). */
	double deficit(Creature who, Player except, long now)
	{
		return Math.max(0, who.getMaxHp() - who.getCurrentHp() - incoming(who, except, now));
	}

	/** Another caster already has a {@code kind} cast on its way to {@code targetId}. */
	boolean claimed(Kind kind, int targetId, Player asker, long now)
	{
		synchronized (_intents)
		{
			for (Intent i : _intents)
			{
				if ((i.kind == kind) && (i.targetId == targetId) && (i.caster != asker) && i.alive(now))
				{
					return true;
				}
			}
		}
		return false;
	}

	/** A party heal from anyone in {@code party} other than {@code asker} is on its way. */
	boolean groupHealInFlight(Party party, Player asker, long now)
	{
		synchronized (_intents)
		{
			for (Intent i : _intents)
			{
				if ((i.kind == Kind.GROUP) && (i.caster != asker) && (i.caster.getParty() == party) && i.alive(now))
				{
					return true;
				}
			}
		}
		return false;
	}

	/** The single heal {@code caster} itself is casting right now, or {@code null}. */
	Intent ownHeal(Player caster, long now)
	{
		synchronized (_intents)
		{
			for (Intent i : _intents)
			{
				if ((i.caster == caster) && (i.kind == Kind.HEAL) && i.alive(now))
				{
					return i;
				}
			}
		}
		return null;
	}

	void forget(Intent intent)
	{
		synchronized (_intents)
		{
			_intents.remove(intent);
		}
	}

	// ===== Resurrection and emergency claims =====

	void claimRes(Player caster, Creature corpse, long castMs)
	{
		_resClaims.put(corpse.getObjectId(), new long[]
		{
			caster.getObjectId(),
			System.currentTimeMillis() + Math.min(RES_CLAIM_CAP_MS, castMs + 6000)
		});
	}

	/** Someone other than {@code asker} is raising {@code corpse}, or its revive is already offered. */
	boolean resClaimed(Player corpse, Player asker, long now)
	{
		if (corpse.isReviveRequested())
		{
			return true;
		}
		final long[] claim = _resClaims.get(corpse.getObjectId());
		return (claim != null) && (claim[1] > now) && (claim[0] != asker.getObjectId());
	}

	/** Takes the party's one emergency-skill slot; {@code false} if another healer just used it. */
	boolean claimEmergency(Party party, long now)
	{
		final int key = party.getLeader().getObjectId();
		final Long until = _emergencyClaims.get(key);
		if ((until != null) && (until > now))
		{
			return false;
		}
		_emergencyClaims.put(key, now + EMERGENCY_CLAIM_MS);
		return true;
	}

	// ===== Estimates =====

	/** Cast time in ms as the engine computes it: hit + cool time scaled by casting speed, floored like the engine. */
	static int castTime(Creature caster, Skill skill)
	{
		final int base = skill.getHitTime() + skill.getCoolTime();
		int time = base;
		if (!skill.isStatic())
		{
			time = Formulas.calcAtkSpd(caster, skill, base);
		}
		if (skill.isMagic() && (base > 550) && (time < 550))
		{
			time = 550;
		}
		else if (!skill.isStatic() && (base >= 500) && (time < 500))
		{
			time = 500;
		}
		return time;
	}

	static boolean isPartySkill(Skill skill)
	{
		switch (skill.getTargetType().name())
		{
			case "PARTY":
			case "PARTY_NOTME":
			case "CLAN":
			case "AURA":
			case "AREA":
			{
				return true;
			}
		}
		return false;
	}

	/** HP {@code skill} cast by {@code caster} would restore on {@code target}, before the missing-HP cap. */
	double estimate(Player caster, Skill skill, Creature target)
	{
		double total = 0;
		for (AbstractEffect effect : skill.getEffects(EffectScope.GENERAL))
		{
			final String name = effect.getClass().getSimpleName();
			if (name.equals("Heal"))
			{
				total += healAmount(caster, skill, target, power(effect));
			}
			else if (name.equals("HealPercent"))
			{
				total += (target.getMaxHp() * power(effect)) / 100.0;
			}
		}
		return total;
	}

	private static double healAmount(Player caster, Skill skill, Creature target, double power)
	{
		double amount = power;
		double shotBonus = 0;
		int mAtkMul;
		final boolean sps = skill.isMagic() && caster.isChargedShot(ShotType.SPIRITSHOTS);
		final boolean bss = skill.isMagic() && caster.isChargedShot(ShotType.BLESSED_SPIRITSHOTS);
		if ((sps || bss) && caster.isMageClass())
		{
			shotBonus = skill.getMpConsume() * (bss ? 2.4 : 1.0);
			mAtkMul = bss ? 4 : 2;
		}
		else
		{
			mAtkMul = bss ? 4 : 2;
		}
		if (skill.isStatic())
		{
			return amount;
		}
		amount += shotBonus + Math.sqrt(mAtkMul * caster.getMAtk(caster, null));
		amount = target.calcStat(Stat.HEAL_EFFECT, amount, null, null);
		final float[] multipliers = ClassBalanceConfig.PLAYER_HEALING_SKILL_MULTIPLIERS;
		final int classId = caster.getPlayerClass().getId();
		if ((skill.getItemConsumeCount() <= 0) && (multipliers != null) && (classId < multipliers.length))
		{
			amount *= multipliers[classId];
		}
		return amount;
	}

	private double power(AbstractEffect effect)
	{
		final Field field = _powerFields.computeIfAbsent(effect.getClass(), c ->
		{
			try
			{
				final Field f = c.getDeclaredField("_power");
				f.setAccessible(true);
				return f;
			}
			catch (ReflectiveOperationException | RuntimeException e)
			{
				return null;
			}
		});
		if (field == null)
		{
			return 0;
		}
		try
		{
			return field.getDouble(effect);
		}
		catch (ReflectiveOperationException | RuntimeException e)
		{
			return 0;
		}
	}
}
