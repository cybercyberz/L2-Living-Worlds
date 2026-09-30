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

import java.lang.reflect.Constructor;
import java.lang.reflect.Field;
import java.lang.reflect.Method;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.logging.Logger;

import org.l2jmobius.gameserver.data.xml.PhantomPlaystyleData;
import org.l2jmobius.gameserver.data.xml.PhantomPlaystyleData.PlayEntry;
import org.l2jmobius.gameserver.data.xml.PhantomPlaystyleData.Playstyle;
import org.l2jmobius.gameserver.managers.PhantomManager;
import org.l2jmobius.gameserver.managers.PhantomPartyManager;
import org.l2jmobius.gameserver.managers.PhantomPlaystyleEngine.PlayState;
import org.l2jmobius.gameserver.model.actor.Player;

/**
 * Every reach into the jar's private phantom state, resolved once. Two independent groups, so one breaking in a future
 * jar only switches off the sections that need it:
 * <ul>
 * <li><b>data</b> - the loaded playstyle map and {@code PlayEntry.paceMs} (skill pacing);</li>
 * <li><b>party</b> - the party manager's member records, its gate helpers, and the engine's per-member state (party
 * tempo and burn phase).</li>
 * </ul>
 */
final class PlaystyleAccess
{
	// Data group.
	Field byClassId;
	Field paceMs;
	boolean dataOk;

	// Party group.
	Field members;
	Field mNpc;
	Field mRole;
	Field mPartied;
	Field mHolding;
	Field mEaseUntil;
	Field mRecoveryUntil;
	Field mPlay;
	Field roleMage;
	Method healerReady;
	Method underAttack;
	Method mpReserve;
	Field psPlaystyle;
	Field psLookedUp;
	Field psNextCastAt;
	Field psGeneration;
	Constructor<Playstyle> playstyleCtor;
	boolean partyOk;

	PlaystyleAccess(Logger log)
	{
		try
		{
			byClassId = field(PhantomPlaystyleData.class, "_byClassId");
			paceMs = field(PlayEntry.class, "paceMs");
			dataOk = true;
		}
		catch (ReflectiveOperationException | RuntimeException e)
		{
			log.warning("Phantom Combat: this GameServer.jar's playstyle data has a different shape (" + e + "); skill pacing stays off.");
		}
		try
		{
			members = field(PhantomPartyManager.class, "_members");
			final Class<?> member = Class.forName("org.l2jmobius.gameserver.managers.PhantomPartyManager$Member");
			mNpc = field(member, "npc");
			mRole = field(member, "role");
			mPartied = field(member, "partied");
			mHolding = field(member, "holding");
			mEaseUntil = field(member, "easeUntil");
			mRecoveryUntil = field(member, "recoveryUntil");
			mPlay = field(member, "play");
			final Class<?> role = Class.forName("org.l2jmobius.gameserver.managers.PhantomManager$PartyRole");
			roleMage = field(role, "mage");
			healerReady = method(PhantomPartyManager.class, "healerReady", member);
			underAttack = method(PhantomPartyManager.class, "underAttack", Player.class);
			mpReserve = method(PhantomPartyManager.class, "mpReserve", role);
			psPlaystyle = field(PlayState.class, "playstyle");
			psLookedUp = field(PlayState.class, "lookedUp");
			psNextCastAt = field(PlayState.class, "nextCastAt");
			psGeneration = field(PlayState.class, "generation");
			playstyleCtor = Playstyle.class.getDeclaredConstructor(String.class, String.class, List.class);
			playstyleCtor.setAccessible(true);
			partyOk = true;
		}
		catch (ReflectiveOperationException | RuntimeException e)
		{
			log.warning("Phantom Combat: this GameServer.jar's party manager has a different shape (" + e + "); party tempo and burn phase stay off.");
		}
	}

	private static Field field(Class<?> owner, String name) throws NoSuchFieldException
	{
		final Field field = owner.getDeclaredField(name);
		field.setAccessible(true);
		return field;
	}

	private static Method method(Class<?> owner, String name, Class<?>... parameters) throws NoSuchMethodException
	{
		final Method method = owner.getDeclaredMethod(name, parameters);
		method.setAccessible(true);
		return method;
	}

	/** Any phantom: a field hunter, a recruited party member, or an alt companion. Never a real player. */
	static boolean isPhantom(Player player)
	{
		return PhantomManager.getInstance().isPhantom(player) || PhantomPartyManager.getInstance().isRecruit(player);
	}

	/** The party manager's live member map (object id -> Member). */
	Map<?, ?> memberMap() throws ReflectiveOperationException
	{
		return (Map<?, ?>) members.get(PhantomPartyManager.getInstance());
	}

	/** The manager's Member record for a partied member whose role is in {@code roles}, else {@code null}. */
	Object dpsMember(Player player, Set<String> roles)
	{
		if (!partyOk || !PhantomPartyManager.getInstance().isRecruit(player))
		{
			return null;
		}
		try
		{
			final Object member = memberMap().get(player.getObjectId());
			if ((member == null) || !mPartied.getBoolean(member) || (mNpc.get(member) != player))
			{
				return null;
			}
			return roles.contains(((Enum<?>) mRole.get(member)).name()) ? member : null;
		}
		catch (ReflectiveOperationException | RuntimeException e)
		{
			return null;
		}
	}
}
