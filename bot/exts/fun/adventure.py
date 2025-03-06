# Adventure command from Python bot.
import asyncio
import json
from contextlib import suppress
from pathlib import Path
from typing import Literal, NotRequired, TypedDict

from discord import Embed, File, HTTPException, Message, Reaction, User
from discord.ext import commands
from discord.ext.commands import Cog as DiscordCog, Context, clean_content
from pydis_core.utils.logging import get_logger
from pydis_core.utils.scheduling import create_task

from bot import constants
from bot.bot import Bot

log = get_logger(__name__)

class GameInfo(TypedDict):
    """A dictionary containing the game information. Used in `available_games.json`."""

    id: str
    name: str
    description: str
    color: str
    time: int


BASE_PATH = "bot/resources/fun/adventures"

AVAILABLE_GAMES: list[GameInfo] = json.loads(
    Path(f"{BASE_PATH}/available_games.json").read_text("utf8")
)

AVAILABLE_GAMES_DICT = {game["id"]: game for game in AVAILABLE_GAMES}


class OptionData(TypedDict):
    """A dictionary containing the options data of the game. Part of the RoomData dictionary."""

    text: str
    leads_to: str
    emoji: str
    requires_effect: NotRequired[str]
    effect_restricts: NotRequired[str]
    effect: NotRequired[str]


class RoomData(TypedDict):
    """A dictionary containing the room data of the game. Part of the AdventureData dictionary."""

    text: str
    picture: str | None
    options: list[OptionData]


class EndRoomData(TypedDict):
    """
    A dictionary containing the ending room data of the game.

    Variant of the RoomData dictionary, also part of the AdventureData dictionary.
    """

    text: str
    type: Literal["end"]
    emoji: str


class GameData(TypedDict):
    """
    A dictionary containing the game data, serialized from a JSON file in `resources/fun/adventures`.

    The keys are the room names, and the values are dictionaries containing the room data,
    which can be either a RoomData or an EndRoomData.

    There must exist only one "start" key in the dictionary. However, there can be multiple endings, i.e.,
    EndRoomData.
    """

    start: RoomData
    other_rooms: dict[str, RoomData | EndRoomData]


class GameCodeNotFoundError(ValueError):
    """Raised when a GameSession code doesn't exist."""

    def __init__(
        self,
        arg: str,
    ) -> None:
        super().__init__(arg)


class GameSession:
    """An interactive session for the Adventure RPG game."""

    def __init__(
        self,
        ctx: Context,
        game_code_or_index: str | None = None,
    ):
        """Creates an instance of the GameSession class."""
        self._ctx = ctx
        self._bot = ctx.bot

        # set the game details/ game codes required for the session
        self.game_code = game_code_or_index
        self.game_data = None
        self.game_info = None
        if game_code_or_index:
            self.game_code = self._parse_game_code(game_code_or_index)
            self.game_info = self._get_game_info()
            self.game_data = self._get_game_data()

        # store relevant discord info
        self.author = ctx.author
        self.destination = ctx.channel
        self.message = None

        # init session states
        self._current_room: str = "start"
        self._path: list[str] = [self._current_room]
        self._choices: list[str] = []
        self._effects: list[str] = []
        self._showing_logs: bool = False

        # session settings
        self._timeout_seconds = 30 if self.game_info is None else self.game_info["time"]
        self.timeout_message = (
            f"⏳ Hint: time is running out! You must make a choice within {self._timeout_seconds} seconds."
        )
        self._timeout_task = None
        self.reset_timeout()
        self.ending_reactions = {"replay": "🔄", "log": "📖"}

    def _parse_game_code(self, game_code_or_index: str) -> str:
        """Returns the actual game code for the given index/ game code."""
        # sanitize the game code to prevent directory traversal attacks.
        game_code = Path(game_code_or_index).name

        # convert index to game code if it's a valid number that is in range.
        # otherwise, return the game code as is, assuming it's a valid game code.
        # if game code is not valid, errors will be raised later when trying to load the game info.
        try:
            index = int(game_code_or_index)
            if 1 <= index <= len(AVAILABLE_GAMES):
                game_code = AVAILABLE_GAMES[index - 1]["id"]
        except (ValueError, IndexError):
            pass

        return game_code

    def _get_game_data(self) -> GameData | None:
        """Returns the game data for the given game code."""
        game_code = self.game_code

        # load the game data from the JSON file
        try:
            game_data = json.loads(
                Path(f"{BASE_PATH}/{game_code}.json").read_text("utf8")
            )
            return game_data
        except FileNotFoundError:
            log.error(
                "Game located in `available_games.json`, but game data not found. Game code: %s",
                game_code
            )
            raise GameCodeNotFoundError(f"Game code `{game_code}` not found.")

    def _get_game_info(self) -> GameInfo:
        """Returns the game info for the given game code."""
        game_code = self.game_code

        try:
            return AVAILABLE_GAMES_DICT[game_code]
        except KeyError:
            raise GameCodeNotFoundError(f"Game code `{game_code}` not found.")

    async def notify_timeout(self) -> None:
        """Notifies the user that the session has timed out."""
        await self.message.edit(content="⏰ You took too long to make a choice! The game has ended. :(")

    async def timeout(self) -> None:
        """Waits for a set number of seconds, then stops the game session."""
        await asyncio.sleep(self._timeout_seconds)
        if not self.is_in_ending_room:
            await self.notify_timeout()
        await self.message.clear_reactions()
        await self.stop()

    def cancel_timeout(self) -> None:
        """Cancels the timeout task."""
        if self._timeout_task and not self._timeout_task.cancelled():
            self._timeout_task.cancel()

    def reset_timeout(self) -> None:
        """Cancels the original timeout task and sets it again from the start."""
        self.cancel_timeout()

        # recreate the timeout task
        self._timeout_task = create_task(self.timeout())

    async def send_available_game_codes(self) -> None:
        """Sends a list of all available game codes."""
        available_game_codes = "\n\n".join(
            f"{index}. **{game['name']}** (`{game['id']}`)\n*{game['description']}*"
            for index, game in enumerate(AVAILABLE_GAMES, start=1)
        )

        embed = Embed(
            title="📋 Available Games",
            description=available_game_codes,
            colour=constants.Colours.soft_red,
        )

        embed.set_footer(text="💡 Hint: use `.adventure [game_code]` or `.adventure [index]` to start a game.")

        await self.destination.send(embed=embed)

    async def on_reaction_add(self, reaction: Reaction, user: User) -> None:
        """Event handler for when reactions are added on the game message."""
        # ensure it was the relevant session message
        if reaction.message.id != self.message.id:
            return

        # ensure it was the session author who reacted
        if user.id != self.author.id:
            return

        emoji = str(reaction.emoji)

        # check if valid action
        if self.is_in_ending_room:
            if emoji not in self.ending_reactions.values():
                return
        elif self.is_showing_logs:
            if emoji not in self.ending_reactions["replay"]:
                return
        else:
            acceptable_emojis = [option["emoji"] for option in self.available_options]
            if emoji not in acceptable_emojis:
                return

        self.reset_timeout()

        # remove all the reactions to prep for re-use
        with suppress(HTTPException):
            await self.message.clear_reactions()

        # Run relevant action method
        if self.is_in_ending_room and emoji == "🔄":
            # Restart the game, by creating a new session and attaching it to the same message.
            await self.stop()
            await self.start(self._ctx, self.game_code, self.message)
            # restart the game from log menu
            if self.is_showing_logs:
                self._showing_logs = not self._showing_logs
        elif self.is_in_ending_room and emoji == "📖":
            # Show the user the choices they made during the game.
            self._showing_logs = not self._showing_logs

            await self.update_message()
        else:
            all_emojis = [option["emoji"] for option in self.all_options]

            await self.pick_option(all_emojis.index(emoji))

    async def on_message_delete(self, message: Message) -> None:
        """Closes the game session when the game message is deleted."""
        if message.id == self.message.id:
            await self.stop()

    async def prepare(self) -> None:
        """Sets up the game events, message and reactions."""
        if self.game_data:
            await self.update_message()
            self._bot.add_listener(self.on_reaction_add)
            self._bot.add_listener(self.on_message_delete)
        else:
            await self.send_available_game_codes()


    async def add_reactions(self) -> None:
        """Adds the relevant reactions to the message based on if options are available in the current room."""
        if self.is_in_ending_room:
            return

        pickable_emojis = [option["emoji"] for option in self.available_options]

        for reaction in pickable_emojis:
            await self.message.add_reaction(reaction)

    async def add_ending_reactions(self) -> None:
        """Adds the relevant reactions to the ending message which includes a replay reaction."""
        if not self.is_in_ending_room:
            return

        for reaction in self.ending_reactions.values():
            await self.message.add_reaction(reaction)

    async def add_log_reactions(self) -> None:
        """Adds the replay function to the log message."""
        if not self.is_showing_logs:
            return

        await self.message.add_reaction(self.ending_reactions["replay"])

    def _format_room_data(self, room_data: RoomData) -> str:
        """Formats the room data into a string for the embed description."""
        text = room_data["text"]

        formatted_options = "\n".join(
            f"{option["emoji"]} {option["text"]}"
            if option in self.available_options
            else "🔒 ***This option is locked***"
            for option in self.all_options
        )

        return f"{text}\n\n{formatted_options}"

    def _format_log_data(self, choices: list[OptionData], game_name: str) -> str:
        """Formats the choice data into a string for the embed description."""
        choices_description = "\n".join(
        f"{index + 1}. {choice['emoji']} {choice['text']}"
        + (f" (Effect: {choice['effect']})" if "effect" in choice else "")
        for index, choice in enumerate(choices)
        )

        return f"**{game_name}**\n{choices_description}"

    def embed_message(self, room_data: RoomData | EndRoomData, choices: list[OptionData]) -> Embed:
        """Returns an Embed with the requested room data formatted within."""
        embed = Embed()
        embed.color = int(self.game_info["color"], base=16)

        current_game_name = AVAILABLE_GAMES_DICT[self.game_code]["name"]

        if self.is_in_ending_room and not self.is_showing_logs:
            embed.description = room_data["text"]
            emoji = room_data["emoji"]
            embed.set_author(name=f"Game ended! {emoji}")
            embed.set_footer(
                text=(
                    f"✨ Thanks for playing {current_game_name}!\n"
                    " - use 🔄 to play again.\n"
                    " - use 📖 to see the choices you made"
                )
            )
        elif self.is_showing_logs:
            embed.description = self._format_log_data(choices, current_game_name)
            embed.set_author(name="📖 Game Log")
            embed.set_footer(
                text=(
                    f"✨ Thanks for playing {current_game_name}!\n"
                    " - use 🔄 to play again.\n"
                )
            )
        else:
            embed.description = self._format_room_data(room_data)
            embed.set_author(name=current_game_name)
            embed.set_footer(text=self.timeout_message)

        return embed

    async def update_message(self) -> None:
        """Sends the initial message, or changes the existing one to the given room ID."""
        embed_message = self.embed_message(self.current_room_data, self._choices)

        file = None
        if self.current_room_data.get("picture"):
            image_path = f"bot/resources/fun/adventures/images/{self.current_room_data['picture']}"
            file = File(image_path, filename="image.jpeg")
            embed_message.set_image(url="attachment://image.jpeg")

        if not self.message:
            self.message = await self.destination.send(file=file, embed=embed_message)
        else:
            if file:
                await self.message.edit(embed=embed_message, attachments=[file])
            else:
                await self.message.edit(embed=embed_message, attachments=[])

        if self.is_in_ending_room and not self.is_showing_logs:
            await self.add_ending_reactions()
        elif self.is_showing_logs:
            await self.add_log_reactions()
        else:
            await self.add_reactions()

    @classmethod
    async def start(
        cls,
        ctx: Context,
        game_code_or_index: str | None = None,
        message: Message | None = None
        ) -> "GameSession":
        """Create and begin a game session based on the given game code."""
        session = cls(ctx, game_code_or_index)

        # Start the session with the given message
        if message:
            session.message = message

        await session.prepare()

        return session

    async def stop(self) -> None:
        """Stops the game session, clean up by removing event listeners."""
        self.cancel_timeout()
        self._bot.remove_listener(self.on_reaction_add)
        self._bot.remove_listener(self.on_message_delete)

    @property
    def is_in_ending_room(self) -> bool:
        """Check if the game has ended."""
        return self.current_room_data.get("type") == "end"

    @property
    def is_showing_logs(self) -> bool:
        """Check if the player is shown logs."""
        return self._showing_logs and self.is_in_ending_room

    @property
    def all_options(self) -> list[OptionData]:
        """Get all options in the current room."""
        return self.current_room_data.get("options", [])

    @property
    def available_options(self) -> bool:
        """
        Get "available" options in the current room.

        This filters out options that require an effect that the user doesn't have or options that restrict an effect.
        """
        filtered_options = filter(
            lambda option: (
                "requires_effect" not in option or option.get("requires_effect") in self._effects
            ) and (
                "effect_restricts" not in option or option.get("effect_restricts") not in self._effects
            ),
            self.all_options
        )

        return filtered_options

    @property
    def current_room_data(self) -> RoomData | EndRoomData:
        """Get the current room data."""
        current_room = self._current_room

        if current_room == "start":
            return self.game_data[current_room]

        return self.game_data["other_rooms"][current_room]

    async def pick_option(self, index: int) -> None:
        """Event that is called when the user picks an option."""
        chosen_option = self.all_options[index]

        next_room = chosen_option["leads_to"]
        new_effect = chosen_option.get("effect")

        # update all the game states
        self._path.append(next_room)
        self._current_room = next_room

        if new_effect:
            self._effects.append(new_effect)

        self._choices.append(chosen_option)

        # update the message with the new room
        await self.update_message()


class Adventure(DiscordCog):
    """Custom Embed for Adventure RPG games."""

    @commands.command(name="adventure")
    async def new_adventure(self, ctx: Context, game_code_or_index: str | None = None) -> None:
        """Wanted to slay a dragon? Embark on an exciting journey through text-based RPG adventure."""
        if isinstance(game_code_or_index, str):
            # prevent malicious pings and mentions
            sanitiser = clean_content(fix_channel_mentions=True)
            game_code_or_index = await sanitiser.convert(ctx, game_code_or_index)

            # quality of life: if the user accidentally wraps the game code in backticks, process it anyway
            game_code_or_index = game_code_or_index.strip("`")
        try:
            await GameSession.start(ctx, game_code_or_index)
        except GameCodeNotFoundError as error:
            await ctx.send(str(error))

    @commands.command(name="adventures")
    async def list_adventures(self, ctx: Context) -> None:
        """List all available adventure games."""
        await GameSession.start(ctx, None)


async def setup(bot: Bot) -> None:
    """Load the Adventure cog."""
    await bot.add_cog(Adventure(bot))
