
import unittest
import unittest.mock

from bot.exts.fun import adventure
from tests import helpers


class AdventureCogTests(unittest.IsolatedAsyncioTestCase):
    """Tests the Adventure Game cog."""

    def setUp(self):
        """Sets up fresh objects for each test."""
        self.bot = helpers.MockBot()

        self.cog = adventure.Adventure()

        self.sample_game = "three_little_pigs"
        self.no_game = "no_game"
        self.ctx = helpers.MockContext(bot=self.bot)

    async def test_new_adventure_game_not_found(self):
        """Test if the `new_adventure` command correctly returns the error message when game not found."""

        await self.cog.new_adventure(self.cog, self.ctx, self.no_game)

        self.ctx.send.assert_called_once()
        message = self.ctx.send.call_args.args[0]
        self.assertEqual(message, f'Game code "{self.no_game}" not found.')

    async def test_new_adventure_game_found(self):
        """Test if the `new_adventure` command does not print any error message when game found."""

        await self.cog.new_adventure(self.cog, self.ctx, self.sample_game)

        self.ctx.send.assert_not_called()

    async def test_get_game_data_game_found(self):
        """Test if the `_get_game_data` command returns a valid dictionary of a story containing start and ending_1 keys."""  # noqa: E501
        game_session = adventure.GameSession(self.ctx, self.sample_game)

        story = game_session._get_game_data(self.sample_game)
        self.assertIn("start", story)
        self.assertIn("ending_1", story)

    async def test_get_game_data_game_not_found(self):
        """Test if the `_get_game_data` command returns a GameCodeNotFoundError if the game_code does not exist."""
        game_session = adventure.GameSession(self.ctx, self.sample_game)

        with self.assertRaises(adventure.GameCodeNotFoundError):
            await game_session._get_game_data(self.no_game)


    async def test_embed_message_footer(self):
        """Test if the `embed_message` command returns an embed with "time running out" hint in the footer."""
        game_session = adventure.GameSession(self.ctx, self.sample_game)

        message = game_session.embed_message(game_session.game_data["start"])
        self.assertEqual(message.footer.text,"⏳ Hint: time is running out! You must make a choice within 60 seconds.")
