"""Contains the Cog that receives discord.py events and defers most actions to other files in the module."""

import discord
from discord.ext import commands

from bot import constants
from bot.bot import Bot
from bot.exts.help_channels import _caches, _channel, _message
from bot.log import get_logger

log = get_logger(__name__)


class HelpForum(commands.Cog):
    """
    Manage the help channel forum of the guild.

    This system uses Discord's native forum channel feature to handle most of the logic.

    The purpose of this cog is to add additional features, such as stats collection, old post locking
    and helpful automated messages.
    """

    def __init__(self, bot: Bot):
        self.bot = bot
        self.help_forum_channel_id = constants.Channels.help_system_forum

    async def close_check(self, ctx: commands.Context) -> bool:
        """Return True if the channel is a help post, and the user is the claimant or has a whitelisted role."""
        if not _channel.is_help_forum_post(ctx.channel):
            return False

        if ctx.author.id == ctx.channel.owner_id:
            log.trace(f"{ctx.author} is the help channel claimant, passing the check for dormant.")
            self.bot.stats.incr("help.dormant_invoke.claimant")
            return True

        log.trace(f"{ctx.author} is not the help channel claimant, checking roles.")
        has_role = await commands.has_any_role(*constants.HelpChannels.cmd_whitelist).predicate(ctx)
        if has_role:
            self.bot.stats.incr("help.dormant_invoke.staff")
        return has_role

    @commands.group(name="help-forum")
    async def help_forum_group(self,  ctx: commands.Context) -> None:
        """A group of commands that help manage our help forum system."""
        if not ctx.invoked_subcommand:
            await ctx.send_help(ctx.command)

    @help_forum_group.command(name="close", root_aliases=("close", "dormant", "solved"))
    async def close_command(self, ctx: commands.Context) -> None:
        """
        Make the help post this command was called in dormant.

        May only be invoked by the channel's claimant or by staff.
        """
        # Don't use a discord.py check because the check needs to fail silently.
        if await self.close_check(ctx):
            log.info(f"Close command invoked by {ctx.author} in #{ctx.channel}.")
            await _channel.help_thread_closed(ctx.channel)

    @help_forum_group.command(name="dm", root_aliases=("helpdm",))
    async def help_dm_command(
        self,
        ctx: commands.Context,
        state_bool: bool,
    ) -> None:
        """
        Allows user to toggle "Helping" DMs.

        If this is set to on the user will receive a dm for the channel they are participating in.
        If this is set to off the user will not receive a dm for channel that they are participating in.
        """
        state_str = "ON" if state_bool else "OFF"

        if state_bool == await _caches.help_dm.get(ctx.author.id, False):
            await ctx.send(f"{constants.Emojis.cross_mark} {ctx.author.mention} Help DMs are already {state_str}")
            return

        if state_bool:
            await _caches.help_dm.set(ctx.author.id, True)
        else:
            await _caches.help_dm.delete(ctx.author.id)
        await ctx.send(f"{constants.Emojis.ok_hand} {ctx.author.mention} Help DMs {state_str}!")

    @help_forum_group.command(name="title", root_aliases=("title",))
    async def rename_help_post(self, ctx: commands.Context, *, title: str) -> None:
        """Rename the help post to the provided title."""
        if not _channel.is_help_forum_post(ctx.channel):
            # Silently fail in channels other than help posts
            return

        if not await commands.has_any_role(constants.Roles.helpers).predicate(ctx):
            # Silently fail for non-helpers
            return

        await ctx.channel.edit(name=title)

    @commands.Cog.listener()
    async def on_thread_create(self, thread: discord.Thread) -> None:
        """Defer application of new post logic for posts the help forum to the _channel helper."""
        if thread.parent_id == self.help_forum_channel_id:
            await _channel.help_thread_opened(thread)

    @commands.Cog.listener()
    async def on_thread_update(self, before: discord.Thread, after: discord.Thread) -> None:
        """Defer application archive logic for posts in the help forum to the _channel helper."""
        if after.parent_id != self.help_forum_channel_id:
            return
        if not before.archived and after.archived:
            await _channel.help_thread_archived(after)

    @commands.Cog.listener()
    async def on_raw_thread_delete(self, deleted_thread_event: discord.RawThreadDeleteEvent) -> None:
        """Defer application of new post logic for posts the help forum to the _channel helper."""
        if deleted_thread_event.parent_id == self.help_forum_channel_id:
            await _channel.help_thread_deleted(deleted_thread_event)

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        """Defer application of new message logic for messages in the help forum to the _message helper."""
        if not _channel.is_help_forum_post(message.channel):
            return None

        await _message.notify_session_participants(message)

        if message.author.id != message.channel.owner_id:
            await _caches.posts_with_non_claimant_messages.set(message.channel.id, "sentinel")
