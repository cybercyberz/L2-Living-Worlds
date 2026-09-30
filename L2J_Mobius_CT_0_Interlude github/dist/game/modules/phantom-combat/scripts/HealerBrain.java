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

import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.logging.Logger;

import org.l2jmobius.gameserver.managers.PhantomBuffs;
import org.l2jmobius.gameserver.managers.PhantomManager;
import org.l2jmobius.gameserver.managers.PhantomManager.PartyRole;
import org.l2jmobius.gameserver.model.World;
import org.l2jmobius.gameserver.model.actor.Creature;
import org.l2jmobius.gameserver.model.actor.Player;
import org.l2jmobius.gameserver.model.actor.Summon;
import org.l2jmobius.gameserver.model.actor.instance.Monster;
import org.l2jmobius.gameserver.model.effects.AbstractEffect;
import org.l2jmobius.gameserver.model.groups.Party;
import org.l2jmobius.gameserver.model.skill.AbnormalType;
import org.l2jmobius.gameserver.model.skill.BuffInfo;
import org.l2jmobius.gameserver.model.skill.EffectScope;
import org.l2jmobius.gameserver.model.skill.Skill;

/**
 * Each recruited healer's own decision, several times a second, from what it knows about the party ({@link PartyBoard}).
 * <p>
 * A healer looks at every member from its own position, MP, kit and cooldowns, and does the first thing that is
 * needed, in this order: save a dying member, answer a party-wide crisis, cleanse, raise the dead, group heal, single
 * heal, restore MP. What it starts goes into the board's ledger through the skill-use event, so the next healer sees
 * that member as covered and picks someone else. When nothing is needed it does nothing, and the party manager keeps
 * handling buffs, following, resting and orders.
 * <p>
 * It also judges the manager's own support casts ({@link #wasted}): a heal on a member that is already covered, a second
 * group heal, or a res, cleanse or recharge someone else already started is stopped before it costs MP.
 */
final class HealerBrain
{
	// Healer-role skills (all levels share the id).
	private static final int HEAL = 1011;
	private static final int BATTLE_HEAL = 1015;
	private static final int GREATER_HEAL = 1217;
	private static final int GREATER_BATTLE_HEAL = 1218;
	private static final int MAJOR_HEAL = 1401;
	private static final int VITALIZE = 1020;
	private static final int RESTORE_LIFE = 1258;
	private static final int GROUP_HEAL = 1027;
	private static final int GREATER_GROUP_HEAL = 1219;
	private static final int MAJOR_GROUP_HEAL = 1402;
	private static final int BENEDICTION = 1271;
	private static final int BALANCE_LIFE = 1335;
	private static final int CELESTIAL_SHIELD = 1418;
	private static final int RESURRECTION = 1016;
	private static final int CURE_POISON = 1012;
	private static final int PURIFY = 1018;
	private static final int CLEANSE = 1409;
	private static final int RECHARGE = 1013;
	private static final int MASS_RECHARGE = 1428;
	private static final int INVOCATION = 1430;

	private static final int[] SINGLE_HEALS =
	{
		BATTLE_HEAL,
		GREATER_BATTLE_HEAL,
		HEAL,
		MAJOR_HEAL,
		VITALIZE,
		GREATER_HEAL,
		RESTORE_LIFE
	};
	private static final int[] GROUP_HEALS =
	{
		GROUP_HEAL,
		GREATER_GROUP_HEAL,
		MAJOR_GROUP_HEAL
	};

	/** The party manager's support range: members further away are not this healer's to heal. */
	private static final int SUPPORT_RANGE = 900;
	/** A reagent (Spirit Ore and the like) weighs this much MP when comparing heal costs. */
	private static final int REAGENT_MP = 20;
	/** A heal is "fast" at or under this cast time. */
	private static final int FAST_CAST_MS = 2500;
	/** Recharge: mana users under this MP% (raid: the higher one) get a refill. */
	private static final int RECHARGE_MP_PERCENT = 45;
	private static final int RECHARGE_RAID_MP_PERCENT = 65;

	private final PlaystyleAccess _access;
	private final PartyBoard _board;
	private final Logger _log;
	private final double _critical; // fraction of max HP
	private final double _minHeal; // fraction of max HP
	private final double _overheal; // allowed estimate / need
	private final int _groupMin;
	private final boolean _emergency;
	private final boolean _veto;
	private final boolean _debug;
	/** Set while this class issues a cast, so the veto never stops the healer's own decision. */
	private final ThreadLocal<Player> _issuing = new ThreadLocal<>();
	private long _lastVetoLog;

	HealerBrain(PlaystyleAccess access, PartyBoard board, Logger log, int criticalPercent, int minHealPercent, int overhealLimitPercent, int groupMin, boolean emergency, boolean veto, boolean debug)
	{
		_access = access;
		_board = board;
		_log = log;
		_critical = criticalPercent / 100.0;
		_minHeal = minHealPercent / 100.0;
		_overheal = overhealLimitPercent / 100.0;
		_groupMin = groupMin;
		_emergency = emergency;
		_veto = veto;
		_debug = debug;
	}

	/** One decision round for every recruited healer. */
	void tick()
	{
		final long now = System.currentTimeMillis();
		_board.sweep(now);
		final Map<?, ?> members;
		try
		{
			members = _access.memberMap();
		}
		catch (ReflectiveOperationException | RuntimeException e)
		{
			return;
		}
		for (Object member : members.values())
		{
			try
			{
				tickHealer(member, now);
			}
			catch (ReflectiveOperationException | RuntimeException e)
			{
				if (_debug)
				{
					_log.warning("Phantom Combat: healer tick failed: " + e);
				}
			}
		}
	}

	private void tickHealer(Object member, long now) throws ReflectiveOperationException
	{
		if ((_access.mRole.get(member) != PartyRole.HEALER) || !_access.mPartied.getBoolean(member))
		{
			return;
		}
		final Player npc = (Player) _access.mNpc.get(member);
		final Party party = npc.getParty();
		if (npc.isDead() || (party == null))
		{
			return;
		}
		if (npc.isCastingNow())
		{
			cancelIfCovered(npc, now);
			return;
		}
		if (servingOrder(member) || _access.hOlympiadHeld.getBoolean(member) || npc.isInOlympiadMode() || PhantomManager.getInstance().isPvpEngaged(npc))
		{
			return; // the manager is carrying out an order or another system owns the member
		}
		final Action action = decide(npc, party, now);
		if (action == null)
		{
			return;
		}
		if (npc.isSitting())
		{
			if (action.urgent)
			{
				npc.standUp(); // cast on the next round, once standing
			}
			return; // routine work doesn't break an MP rest
		}
		if (npc.isMovementDisabled())
		{
			return; // stunned, rooted or held
		}
		cast(npc, action, now);
	}

	private boolean servingOrder(Object member) throws ReflectiveOperationException
	{
		return _access.hHealNow.getBoolean(member) || (_access.hPendingBuff.get(member) != null) || (_access.hRechargeTarget.get(member) != null) || _access.hRebuffing.getBoolean(member);
	}

	private void cast(Player npc, Action action, long now)
	{
		if (action.skill.getId() == RESURRECTION)
		{
			PhantomBuffs.claimRes(action.target.getObjectId(), npc.getObjectId(), 12000); // the manager's own rezzers respect this claim too
		}
		if (_debug)
		{
			_log.info("Phantom Combat: " + npc.getName() + " " + action.why + ": " + action.skill.getName() + " -> " + action.target.getName() //
				+ " (hp " + (int) action.target.getCurrentHp() + "/" + action.target.getMaxHp() + ", incoming " + (int) _board.incoming(action.target, npc, now) + ")");
		}
		npc.setTarget(action.target);
		_issuing.set(npc);
		try
		{
			npc.doCast(action.skill);
		}
		finally
		{
			_issuing.remove();
		}
	}

	/** A slow heal whose target another caster has already covered is stopped, as a human healer would. */
	private void cancelIfCovered(Player npc, long now)
	{
		final PartyBoard.Intent own = _board.ownHeal(npc, now);
		if ((own == null) || ((own.landAt - now) < 1000) || (npc.getLastSkillCast() == null) || (npc.getLastSkillCast().getHitTime() < 4000))
		{
			return;
		}
		if (own.target.isDead() || (_board.deficit(own.target, npc, now) < (0.25 * own.amount)))
		{
			npc.abortCast();
			_board.forget(own);
			if (_debug)
			{
				_log.info("Phantom Combat: " + npc.getName() + " cancelled " + npc.getLastSkillCast().getName() + " on " + own.target.getName() + ": already covered.");
			}
		}
	}

	// ===== The decision =====

	private static final class Action
	{
		final Skill skill;
		final Creature target;
		final boolean urgent;
		final String why;

		Action(Skill skill, Creature target, boolean urgent, String why)
		{
			this.skill = skill;
			this.target = target;
			this.urgent = urgent;
			this.why = why;
		}
	}

	private Action decide(Player npc, Party party, long now)
	{
		final List<Player> mates = new ArrayList<>();
		final List<Player> corpses = new ArrayList<>();
		for (Player p : party.getMembers())
		{
			if (npc.calculateDistance2D(p) > SUPPORT_RANGE)
			{
				continue;
			}
			(p.isDead() ? corpses : mates).add(p);
		}

		Action action = saveALife(npc, mates, now);
		if ((action == null) && _emergency)
		{
			action = partyEmergency(npc, party, now);
		}
		if (action == null)
		{
			action = cleanse(npc, mates, now);
		}
		if (action == null)
		{
			action = raise(npc, corpses, now);
		}
		if (action == null)
		{
			action = groupHeal(npc, party, now);
		}
		if (action == null)
		{
			action = singleHeal(npc, mates, now);
		}
		if (action == null)
		{
			action = restoreMp(npc, mates, now);
		}
		return action;
	}

	/** 1. The member whose predicted HP, when this healer's fastest heal could land, is lowest and below critical. */
	private Action saveALife(Player npc, List<Player> mates, long now)
	{
		final List<Skill> heals = castableSingles(npc);
		if (heals.isEmpty())
		{
			return null;
		}
		int fastest = Integer.MAX_VALUE;
		for (Skill s : heals)
		{
			fastest = Math.min(fastest, PartyBoard.castTime(npc, s));
		}
		Player worst = null;
		double worstPredicted = 0;
		double worstFraction = _critical;
		for (Player p : mates)
		{
			final double predicted = p.getCurrentHp() + _board.incoming(p, npc, now) - ((_board.dtps(p, now) * fastest) / 1000.0);
			final double fraction = predicted / p.getMaxHp();
			if (fraction < worstFraction)
			{
				worst = p;
				worstFraction = fraction;
				worstPredicted = predicted;
			}
		}
		if (worst == null)
		{
			return null;
		}

		// Heals can't keep up with a tank or leader about to die: make it invincible first.
		final Skill shield = npc.getKnownSkill(CELESTIAL_SHIELD);
		final double dtps = _board.dtps(worst, now);
		if (_emergency && (shield != null) && castable(npc, shield, worst) && isTankOrLeader(worst) && (worst.getCurrentHp() < (0.25 * worst.getMaxHp())) //
			&& ((dtps * PartyBoard.castTime(npc, shield)) < (worst.getCurrentHp() * 1000)) && ((dtps * 6) > (worst.getCurrentHp() + _board.incoming(worst, npc, now))))
		{
			return new Action(shield, worst, true, "shields");
		}

		// The fastest heal that lifts it back over critical; if none does, the most HP per second.
		final double needed = (_critical * worst.getMaxHp()) - worstPredicted;
		Skill best = null;
		int bestTime = Integer.MAX_VALUE;
		Skill strongest = null;
		double strongestRate = 0;
		for (Skill s : heals)
		{
			if (!inRange(npc, s, worst))
			{
				continue;
			}
			final double amount = _board.estimate(npc, s, worst);
			final int time = PartyBoard.castTime(npc, s);
			if ((amount >= needed) && ((time < bestTime) || ((time == bestTime) && (cost(s) < cost(best)))))
			{
				best = s;
				bestTime = time;
			}
			final double rate = amount / time;
			if (rate > strongestRate)
			{
				strongest = s;
				strongestRate = rate;
			}
		}
		final Skill chosen = (best != null) ? best : strongest;
		return (chosen == null) ? null : new Action(chosen, worst, true, "saves");
	}

	/** 2. One party-wide cooldown for a party-wide crisis; only one healer spends it. */
	private Action partyEmergency(Player npc, Party party, long now)
	{
		final Skill benediction = npc.getKnownSkill(BENEDICTION);
		if ((benediction != null) && castable(npc, benediction, npc))
		{
			int low = 0;
			for (Player p : party.getMembers())
			{
				if (!p.isDead() && (npc.calculateDistance2D(p) <= benediction.getAffectRange()) && (((p.getCurrentHp() + _board.incoming(p, npc, now)) / p.getMaxHp()) < 0.40))
				{
					low++;
				}
			}
			if ((low >= 3) && _board.claimEmergency(party, now))
			{
				return new Action(benediction, npc, true, "calls Benediction for " + low + " low members");
			}
		}
		final Skill balance = npc.getKnownSkill(BALANCE_LIFE);
		if ((balance != null) && castable(npc, balance, npc))
		{
			double sum = 0;
			double lowest = 1;
			int count = 0;
			for (Player p : party.getMembers())
			{
				if (!p.isDead() && (npc.calculateDistance2D(p) <= balance.getAffectRange()))
				{
					final double fraction = p.getCurrentHp() / p.getMaxHp();
					sum += fraction;
					lowest = Math.min(lowest, fraction);
					count++;
				}
			}
			if ((count >= 3) && (lowest < 0.30) && ((sum / count) > 0.65) && _board.claimEmergency(party, now))
			{
				return new Action(balance, npc, true, "balances party HP");
			}
		}
		return null;
	}

	/** 3. A disabling debuff first (the tank's before anyone's), then poison or bleeding on a hurt member. */
	private Action cleanse(Player npc, List<Player> mates, long now)
	{
		final Skill purify = usable(npc, PURIFY);
		final Skill curePoison = usable(npc, CURE_POISON);
		final Skill vitalize = usable(npc, VITALIZE);
		final Skill cleanse = usable(npc, CLEANSE);
		if ((purify == null) && (curePoison == null) && (vitalize == null) && (cleanse == null))
		{
			return null;
		}
		Action disabling = null;
		Action dot = null;
		for (Player p : mates)
		{
			if (_board.claimed(PartyBoard.Kind.CLEANSE, p.getObjectId(), npc, now))
			{
				continue;
			}
			boolean held = false;
			boolean poison = false;
			boolean bleed = false;
			int debuffs = 0;
			for (BuffInfo info : p.getEffectList().getDebuffs())
			{
				debuffs++;
				final AbnormalType type = info.getSkill().getAbnormalType();
				final int level = info.getSkill().getAbnormalLevel();
				held |= ((type == AbnormalType.PARALYZE) && (level <= 1)) || ((type == AbnormalType.TURN_STONE) && (level <= 2));
				poison |= (type == AbnormalType.POISON) && (level <= 9);
				bleed |= (type == AbnormalType.BLEEDING) && (level <= 9);
			}
			if (held || ((debuffs >= 3) && isTankOrLeader(p) && (cleanse != null)))
			{
				final Skill s = held && (purify != null) && inRange(npc, purify, p) ? purify : ((cleanse != null) && inRange(npc, cleanse, p) ? cleanse : null);
				if ((s != null) && ((disabling == null) || isTank(p)))
				{
					disabling = new Action(s, p, true, "frees");
				}
			}
			else if ((poison || bleed) && (dot == null) && (p.getCurrentHp() < (0.9 * p.getMaxHp())))
			{
				final boolean hurt = _board.deficit(p, npc, now) >= (0.2 * p.getMaxHp());
				Skill s = null;
				if (hurt && (vitalize != null) && inRange(npc, vitalize, p))
				{
					s = vitalize;
				}
				else if ((purify != null) && inRange(npc, purify, p))
				{
					s = purify;
				}
				else if (poison && !bleed && (curePoison != null) && inRange(npc, curePoison, p))
				{
					s = curePoison;
				}
				if (s != null)
				{
					dot = new Action(s, p, false, "cleanses");
				}
			}
		}
		return (disabling != null) ? disabling : dot;
	}

	/** 4. The unclaimed corpse most worth raising: a human first, then the tank, a healer, anyone. */
	private Action raise(Player npc, List<Player> corpses, long now)
	{
		final Skill res = npc.getKnownSkill(RESURRECTION);
		if ((res == null) || corpses.isEmpty())
		{
			return null;
		}
		Player best = null;
		int bestRank = Integer.MAX_VALUE;
		for (Player corpse : corpses)
		{
			if (_board.resClaimed(corpse, npc, now) || PhantomBuffs.isResClaimed(corpse.getObjectId(), npc.getObjectId(), now) || corpse.isResurrectionBlocked() || !castable(npc, res, corpse))
			{
				continue;
			}
			final int rank = (corpse.getClient() != null) ? 0 : isTank(corpse) ? 1 : (role(corpse) == PartyRole.HEALER) ? 2 : 3;
			if (rank < bestRank)
			{
				best = corpse;
				bestRank = rank;
			}
		}
		return (best == null) ? null : new Action(res, best, true, "raises");
	}

	/** 5. The party heal with the best HP per MP, when enough members still need that much once in-flight heals land. */
	private Action groupHeal(Player npc, Party party, long now)
	{
		if (_board.groupHealInFlight(party, npc, now))
		{
			return null;
		}
		Skill best = null;
		double bestValue = 0;
		int bestCount = 0;
		for (int id : GROUP_HEALS)
		{
			final Skill s = usable(npc, id);
			if (s == null)
			{
				continue;
			}
			final int range = (s.getAffectRange() > 0) ? s.getAffectRange() : 1000;
			int count = 0;
			double landed = 0;
			for (Player p : party.getMembers())
			{
				if (p.isDead() || (npc.calculateDistance2D(p) > range))
				{
					continue;
				}
				final double amount = _board.estimate(npc, s, p);
				final double need = _board.deficit(p, npc, now);
				if (need >= (0.6 * amount))
				{
					count++;
				}
				landed += Math.min(need, amount);
			}
			final double value = landed / cost(s);
			if ((count >= _groupMin) && (value > bestValue))
			{
				best = s;
				bestValue = value;
				bestCount = count;
			}
		}
		return (best == null) ? null : new Action(best, npc, false, "group heals " + bestCount + " members");
	}

	/** 6. The member with the biggest weighted need, and the cheapest heal that fills it without overhealing. */
	private Action singleHeal(Player npc, List<Player> mates, long now)
	{
		final List<Skill> heals = castableSingles(npc);
		if (heals.isEmpty())
		{
			return null;
		}
		final List<Creature> candidates = new ArrayList<>(mates);
		for (Player p : mates)
		{
			final Summon summon = p.getSummon();
			if ((summon != null) && !summon.isDead() && (npc.calculateDistance2D(summon) <= SUPPORT_RANGE))
			{
				candidates.add(summon);
			}
		}
		Creature target = null;
		double targetNeed = 0;
		double bestScore = 0;
		for (Creature c : candidates)
		{
			final double need = _board.deficit(c, npc, now) + (_board.dtps(c, now) * 2);
			if (need < (_minHeal * c.getMaxHp()))
			{
				continue;
			}
			final double score = need * weight(c);
			if (score > bestScore)
			{
				target = c;
				targetNeed = need;
				bestScore = score;
			}
		}
		if (target == null)
		{
			return null;
		}

		// Falling fast: a 5 s heal would land too late to matter.
		final double dtps = _board.dtps(target, now);
		final boolean fallingFast = ((target.getCurrentHp() + _board.incoming(target, npc, now)) - (dtps * 5)) < (0.5 * target.getMaxHp());
		Skill fit = null;
		double fitCost = Double.MAX_VALUE;
		Skill smallest = null;
		double smallestAmount = Double.MAX_VALUE;
		for (int pass = 0; (pass < 2) && (fit == null); pass++)
		{
			for (Skill s : heals)
			{
				if (!inRange(npc, s, target) || ((pass == 0) && fallingFast && (PartyBoard.castTime(npc, s) > FAST_CAST_MS)))
				{
					continue;
				}
				final double amount = _board.estimate(npc, s, target);
				if (amount <= 0)
				{
					continue;
				}
				if (amount < smallestAmount)
				{
					smallest = s;
					smallestAmount = amount;
				}
				if (amount <= (targetNeed * _overheal))
				{
					final double perHp = cost(s) / Math.min(amount, targetNeed);
					if (perHp < fitCost)
					{
						fit = s;
						fitCost = perHp;
					}
				}
			}
		}
		if (fit != null)
		{
			return new Action(fit, target, false, "heals");
		}
		// Every heal is bigger than the need: only worth it when the need is most of the smallest heal.
		if ((smallest != null) && (targetNeed >= (0.7 * smallestAmount)))
		{
			return new Action(smallest, target, false, "tops up");
		}
		return null;
	}

	/** 7. Recharge the most important drained mana user; Mass Recharge for many; Invocation for itself in a lull. */
	private Action restoreMp(Player npc, List<Player> mates, long now)
	{
		final Skill mass = usable(npc, MASS_RECHARGE);
		if ((mass != null) && castable(npc, mass, npc))
		{
			int drained = 0;
			for (Player p : mates)
			{
				if ((p != npc) && (rechargeRank(p) >= 0) && (p.getCurrentMpPercent() < 40))
				{
					drained++;
				}
			}
			if (drained >= 3)
			{
				return new Action(mass, npc, false, "mass recharges " + drained + " members");
			}
		}
		final Skill recharge = usable(npc, RECHARGE);
		if (recharge != null)
		{
			final int threshold = raidEngaged(npc) ? RECHARGE_RAID_MP_PERCENT : RECHARGE_MP_PERCENT;
			Player best = null;
			int bestScore = Integer.MAX_VALUE;
			for (Player p : mates)
			{
				final int rank = rechargeRank(p);
				final int mp = p.getCurrentMpPercent();
				if ((p == npc) || (rank < 0) || (mp >= threshold) || (p.getKnownSkill(RECHARGE) != null) || !inRange(npc, recharge, p) || _board.claimed(PartyBoard.Kind.RECHARGE, p.getObjectId(), npc, now))
				{
					continue;
				}
				final int score = (rank * 1000) + mp;
				if (score < bestScore)
				{
					best = p;
					bestScore = score;
				}
			}
			if (best != null)
			{
				return new Action(recharge, best, false, "recharges");
			}
		}
		final Skill invocation = usable(npc, INVOCATION);
		if ((invocation != null) && (npc.getCurrentMpPercent() < 30) && quiet(npc, mates, now))
		{
			return new Action(invocation, npc, false, "meditates");
		}
		return null;
	}

	// ===== The veto =====

	/**
	 * {@code true} if a support member's cast from the party manager would be wasted, given what is already on its way.
	 * The healer's own decisions, human casts and the manager's direct orders are never judged here.
	 */
	boolean wasted(Player caster, Skill skill, Creature target, long now)
	{
		if (!_veto || (skill == null) || (target == null) || (_issuing.get() == caster) || !PlaystyleAccess.isPhantom(caster))
		{
			return false;
		}
		final Object member;
		try
		{
			member = _access.memberMap().get(caster.getObjectId());
			if ((member == null) || !((PartyRole) _access.mRole.get(member)).isSupport())
			{
				return false;
			}
			if ((skill.getId() == RECHARGE) && (_access.hRechargeTarget.get(member) == target))
			{
				return false; // a "recharge <name>" order
			}
		}
		catch (ReflectiveOperationException | RuntimeException e)
		{
			return false;
		}
		final Party party = caster.getParty();
		for (AbstractEffect effect : skill.getEffects(EffectScope.GENERAL))
		{
			switch (effect.getClass().getSimpleName())
			{
				case "Heal":
				case "HealPercent":
				{
					if (PartyBoard.isPartySkill(skill))
					{
						return logVeto(caster, skill, target, (party != null) && _board.groupHealInFlight(party, caster, now));
					}
					if ((target.getCurrentHp() >= target.getMaxHp()) || (target.getCurrentHp() < (_critical * target.getMaxHp())))
					{
						return false; // a "heal me" at full HP, or a member in real danger
					}
					return logVeto(caster, skill, target, _board.deficit(target, caster, now) < (0.25 * _board.estimate(caster, skill, target)));
				}
				case "Resurrection":
				{
					return logVeto(caster, skill, target, (target instanceof Player) && target.isDead() && _board.resClaimed((Player) target, caster, now));
				}
				case "DispelBySlot":
				case "DispelByCategory":
				{
					return logVeto(caster, skill, target, _board.claimed(PartyBoard.Kind.CLEANSE, target.getObjectId(), caster, now));
				}
				case "ManaHealByLevel":
				{
					return logVeto(caster, skill, target, _board.claimed(PartyBoard.Kind.RECHARGE, target.getObjectId(), caster, now));
				}
			}
		}
		return false;
	}

	private boolean logVeto(Player caster, Skill skill, Creature target, boolean veto)
	{
		if (veto && _debug)
		{
			final long now = System.currentTimeMillis();
			if ((now - _lastVetoLog) > 1000)
			{
				_lastVetoLog = now;
				_log.info("Phantom Combat: stopped " + caster.getName() + "'s " + skill.getName() + " on " + target.getName() + ": already covered.");
			}
		}
		return veto;
	}

	// ===== Helpers =====

	private List<Skill> castableSingles(Player npc)
	{
		final List<Skill> list = new ArrayList<>();
		for (int id : SINGLE_HEALS)
		{
			final Skill s = usable(npc, id);
			if (s != null)
			{
				list.add(s);
			}
		}
		return list;
	}

	/** The known skill, if it is off cooldown and affordable (MP and reagent). */
	private static Skill usable(Player npc, int id)
	{
		final Skill s = npc.getKnownSkill(id);
		if ((s == null) || npc.isSkillDisabled(s) || (npc.getCurrentMp() < (s.getMpConsume() + s.getMpInitialConsume())) || !PhantomBuffs.canAffordReagent(npc, s))
		{
			return null;
		}
		return s;
	}

	private static boolean castable(Player npc, Skill s, Creature target)
	{
		return (usable(npc, s.getId()) != null) && s.checkCondition(npc, target, false);
	}

	/** Within the skill's reach from where the healer stands, so a cast never walks it off its position. */
	private static boolean inRange(Player npc, Skill s, Creature target)
	{
		final int reach = (s.getEffectRange() > 0) ? Math.min(s.getEffectRange(), SUPPORT_RANGE) : Math.max(s.getCastRange(), 0) + 50;
		return npc.calculateDistance2D(target) <= reach;
	}

	private static double cost(Skill s)
	{
		return (s == null) ? Double.MAX_VALUE : Math.max(1, s.getMpConsume() + s.getMpInitialConsume() + (s.getItemConsumeCount() * REAGENT_MP));
	}

	private static PartyRole role(Creature c)
	{
		return (c instanceof Player) ? PhantomManager.roleForClass(((Player) c).getPlayerClass()) : null;
	}

	private static boolean isTank(Creature c)
	{
		return role(c) == PartyRole.TANK;
	}

	private static boolean isTankOrLeader(Player p)
	{
		return isTank(p) || (p.getClient() != null);
	}

	/** Priority weight: the tank soaks, the human is who the party is for, a healer keeps everyone else up. */
	private static double weight(Creature c)
	{
		if (c instanceof Summon)
		{
			return 0.6;
		}
		final Player p = (Player) c;
		if (isTank(p))
		{
			return 1.3;
		}
		if (p.getClient() != null)
		{
			return 1.2;
		}
		return (role(p) == PartyRole.HEALER) ? 1.15 : 1.0;
	}

	/** Recharge order, as the party manager ranks it: healers, tank, other casters and bards, a starved archer; -1 for none. */
	private static int rechargeRank(Player p)
	{
		final PartyRole role = role(p);
		if (role == PartyRole.HEALER)
		{
			return 0;
		}
		if (role == PartyRole.TANK)
		{
			return 1;
		}
		if (role.isSupport() || (role == PartyRole.NUKER) || (role == PartyRole.SINGER) || (role == PartyRole.DANCER))
		{
			return 2;
		}
		return ((role == PartyRole.ARCHER) && (p.getCurrentMpPercent() < 15)) ? 3 : -1;
	}

	private static boolean raidEngaged(Player npc)
	{
		for (Monster m : World.getInstance().getVisibleObjectsInRange(npc, Monster.class, 1500))
		{
			if (m.isRaid() && m.isInCombat() && !m.isDead())
			{
				return true;
			}
		}
		return false;
	}

	/** Nobody in reach is taking damage. */
	private boolean quiet(Player npc, List<Player> mates, long now)
	{
		if (_board.dtps(npc, now) > 0)
		{
			return false;
		}
		for (Player p : mates)
		{
			if (_board.dtps(p, now) > 0)
			{
				return false;
			}
		}
		return true;
	}
}
