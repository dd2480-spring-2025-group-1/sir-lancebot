
import asyncio
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

        self.sample_game_base = "three_little_pigs"
        self.no_game = "no_game"
        self.ctx = helpers.MockContext(bot=self.bot)

    async def test_new_adventure_game_not_found(self):
        """Test if the `new_adventure` command correctly returns the error message when game not found."""

        await self.cog.new_adventure(self.cog, self.ctx, self.no_game)

        self.ctx.send.assert_called_once()
        message = self.ctx.send.call_args.args[0]
        self.assertEqual(message, f"Game code `{self.no_game}` not found.")

    async def test_new_adventure_game_found(self):
        """Test if the `new_adventure` command does not print any error message when game found."""

        await self.cog.new_adventure(self.cog, self.ctx, self.sample_game_base)

        self.ctx.send.assert_not_called()

class AdventureGameSessionTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        """Sets up fresh objects for each test."""
        self.bot = helpers.MockBot()

        self.sample_game_base = "three_little_pigs"
        self.sample_game_locked = "Gurfelts_haunted_mansion"
        self.sample_game_replay = "fruitloop"
        self.sample_game_dragon = "dragon_slayer"
        self.no_game = "no_game"
        self.ctx = helpers.MockContext(bot=self.bot)
        asyncio.run(self._setup_game_session())

    async def _setup_game_session(self):
        """Helper method to ensure event loop is running for async code."""
        self.game_session = adventure.GameSession(self.ctx, self.sample_game_base)

    async def test_get_game_data_game_found(self):
        """Test if the `_get_game_data` command returns a valid dictionary of a story containing start and ending_1 keys."""  # noqa: E501
        self.game_session.game_code = self.sample_game_base

        story = self.game_session._get_game_data()
        self.assertIn("start", story)
        self.assertIn("ending_1", story["other_rooms"])

    async def test_get_game_data_game_not_found(self):
        """Test if the `_get_game_data` command returns a GameCodeNotFoundError if the game_code does not exist."""
        self.game_session.game_code = self.no_game

        with self.assertRaises(adventure.GameCodeNotFoundError):
            await self.game_session._get_game_data()


    async def test_embed_message_footer(self):
        """Test if the `embed_message` command returns an embed with "time running out" hint in the footer."""

        message = self.game_session.embed_message(self.game_session.game_data["start"], self.game_session._choices)
        self.assertEqual(message.footer.text,"⏳ Hint: time is running out! You must make a choice within 30 seconds.")

    async def test_format_room_data(self):
        """Test if the `_format_room_data` command returns a string in the expected format"""

        message = self.game_session._format_room_data(self.game_session.game_data["start"])
        expected_message = (
            "A wolf is on the prowl! You are one of the three little pigs. Choose your starting action:\n\n"
            "🌾 Build a Straw House\n"
            "🪵 Build a Stick House\n"
            "🧱 Build a Brick House"
        )

        # Check if the message has the correct shape
        self.assertEqual(message, expected_message)
        self.assertEqual(message.count("\n"), 4)

    async def test_all_options(self):
        """Test if the `all_options` command returns the expected list of dictionaries"""

        options = self.game_session.all_options
        self.assertIsInstance(options, list)
        for option in options:
            self.assertIsInstance(option, dict)
            self.assertIn("text", option)
            self.assertIn("leads_to", option)
            self.assertIn("emoji", option)

    async def test_is_ending_room_true(self):
        """Test if the `is_ending_room` command returns True when the game session is in the last room"""

        self.game_session._current_room = "ending_1"
        self.assertTrue(self.game_session.is_in_ending_room)

    async def test_is_ending_room_false(self):
        """Test if the `is_ending_room` command returns False when the game session is in the first room"""

        self.assertFalse(self.game_session.is_in_ending_room)

    async def test_available_options(self):
        """Test if the `available_options` method returns all options when the game session is in the first room"""

        filtered_options = self.game_session.available_options
        self.assertEqual(len(list(filtered_options)), 3)

    async def test_parse_game_code_fail_int(self):
        """Test if the `_parse_game_code` method raises a TypeError when given an integer."""

        with self.assertRaises(TypeError):
            self.game_session._parse_game_code(1)

    async def test_parse_game_code_pass(self):
        """Test if the `_parse_game_code` method returns the correct game name when given a valid game code."""

        name = self.game_session._parse_game_code("1")
        self.assertEqual(name, "three_little_pigs")

    async def test_parse_game_code_pass_unknown_game_code(self):
        """Test if the `_parse_game_code` method returns the game code itself when given an unknown game code."""

        name = self.game_session._parse_game_code("999")
        self.assertEqual(name, "999")

    async def test_get_game_info_valid_game_code(self):
        """Test if the `_get_game_info` method returns a dictionary with the expected elements."""

        info = self.game_session._get_game_info()
        self.assertTrue(all(key in info for key in ["id", "name", "description", "color", "time"]))

    async def test_get_game_info_invalid_code(self):
        """Test if the `_get_game_info` method returns a dictionary with the expected elements."""

        self.game_session.game_code = self.no_game
        with self.assertRaises(adventure.GameCodeNotFoundError):
            self.game_session._get_game_info()

    async def test_is_showing_logs_ending_logs(self):
        """Test if the `_is_showing_logs` method returns a true when in an ending room and `_showing_logs` is true."""

        self.game_session._current_room = "ending_2"
        self.game_session._showing_logs = True

        self.assertTrue(self.game_session.is_showing_logs)

    async def test_is_showing_logs_not_ending(self):
        """Test if the `_is_showing_logs` method returns a false when not in ending room and `_showing_logs` is true."""

        self.game_session._showing_logs = True

        self.assertFalse(self.game_session.is_showing_logs)

    async def test_is_showing_logs_ending_no_logs(self):
        """Test if the `_is_showing_logs` method returns a false when in ending room and `_showing_logs` is false."""

        self.game_session._current_room = "ending_2"

        self.assertFalse(self.game_session.is_showing_logs)

    async def test_pick_option_room_advances(self):
        """Test if the `pick_option` method changes the current room."""

        first_room = self.game_session._current_room
        await self.game_session.pick_option(2)
        self.assertNotEqual(first_room, self.game_session._current_room)

    async def test_pick_option_room_advances_to_correct_target(self):
        """Test if the `pick_option` method advances to the desired target room."""

        target = list(self.game_session.available_options)[2]["leads_to"]
        await self.game_session.pick_option(2)
        self.assertEqual(self.game_session._current_room, target)

    async def test_format_log_data(self):
        """Test if the `_format_log_data` method shows the correct path."""

        first_option = self.game_session.all_options[2]["text"]
        await self.game_session.pick_option(2)
        second_option = self.game_session.all_options[1]["text"]
        await self.game_session.pick_option(1)

        self.game_session._showing_logs = True
        log = self.game_session._format_log_data(self.game_session._choices, self.game_session.game_info["name"])
        self.assertIn(self.game_session.game_info["name"],log)
        self.assertIn(first_option,log)
        self.assertIn(second_option,log)
