
import re
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

    async def test_get_game_data_game_not_found(self):
        """Test if the `new_adventure` command correctly returns the error message when game not found."""

        self.assertIsNone(await self.cog.new_adventure(self.cog, self.ctx, self.no_game))
        self.ctx.send.assert_called_once()
        message, kwargs = self.ctx.send.call_args
        self.assertRegex(message[0], re.compile(r'Game code ".*" not found.'))

    async def test_get_game_data_game_found(self):
        """Test if the `new_adventure` command does not print any error message when game found."""

        self.assertIsNone(await self.cog.new_adventure(self.cog, self.ctx, self.sample_game))
        self.ctx.send.assert_not_called()
