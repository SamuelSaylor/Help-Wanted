import asyncio
from io import StringIO

import pytest
import questionary
from prompt_toolkit.input import create_pipe_input
from prompt_toolkit.output import DummyOutput
from prompt_toolkit.output.vt100 import Vt100_Output
from prompt_toolkit.data_structures import Size
from rich.console import Console

from help_wanted.theme import PROMPT_STYLE, boxed_question, themed_console


@pytest.mark.parametrize("kind, keys, expected", [
    ("text", "hello\r", "hello"),
    ("text", "\r", ""),
    ("select", "\x1b[B\r", "Skip"),
    ("checkbox", " \r", ["Python"]),
    ("checkbox", "\r", []),
])
def test_boxed_prompts_preserve_keyboard_input(kind, keys, expected):
    async def run():
        with create_pipe_input() as pipe:
            kwargs = dict(qmark="", style=PROMPT_STYLE, input=pipe, output=DummyOutput())
            if kind != "text":
                kwargs.update(choices=["Python", "Skip"], instruction=" ")
            question = boxed_question(
                getattr(questionary, kind)("", **kwargs), "Your question?",
            )
            pipe.send_text(keys)
            return await question.unsafe_ask_async()

    assert asyncio.run(run()) == expected


def test_console_uses_white_on_black_and_orange_accents():
    console = themed_console()
    assert console.style == "#ffffff on #000000"
    assert console.get_style("accent").color.triplet == (255, 135, 0)


@pytest.mark.parametrize("kind", ["select", "checkbox", "text"])
def test_rendered_prompt_fills_every_cell_with_black(kind):
    async def run():
        with create_pipe_input() as pipe:
            kwargs = dict(qmark="", style=PROMPT_STYLE, input=pipe, output=DummyOutput())
            if kind != "text":
                kwargs.update(choices=["Python", "Skip"], instruction=" ")
            question = boxed_question(
                getattr(questionary, kind)("", **kwargs), "Your question?",
            )
            backgrounds = set()

            def capture(app):
                screen = app.renderer.last_rendered_screen
                if screen is None:
                    return
                for y in range(screen.height):
                    for x in range(80):
                        cell = screen.data_buffer[y][x]
                        attrs = app._merged_style.get_attrs_for_style_str(cell.style)
                        backgrounds.add(attrs.bgcolor)
                pipe.send_text("\r")

            question.application.after_render += capture
            await question.unsafe_ask_async()
            return backgrounds

    assert asyncio.run(run()) == {"000000"}


def test_prompt_emits_literal_black_not_terminal_palette_black():
    async def run():
        with create_pipe_input() as pipe:
            stream = StringIO()
            output = Vt100_Output(stream, lambda: Size(rows=24, columns=80), enable_cpr=False)
            question = boxed_question(questionary.select(
                "", choices=["Python", "Skip"], qmark="", instruction=" ",
                style=PROMPT_STYLE, input=pipe, output=output,
            ), "Your question?")
            pipe.send_text("\r")
            await question.unsafe_ask_async()
            return stream.getvalue()

    assert "48;2;0;0;0" in asyncio.run(run())


@pytest.mark.parametrize("interrupted", [False, True])
def test_terminal_background_covers_unpainted_space_and_restores(monkeypatch, interrupted):
    from help_wanted import theme

    stream = StringIO()
    monkeypatch.setattr(stream, "isatty", lambda: True)
    monkeypatch.setattr("sys.stdout", stream)
    try:
        with theme.terminal_background():
            assert stream.getvalue() == "\x1b]11;#000000\x1b\\"
            if interrupted:
                raise KeyboardInterrupt
    except KeyboardInterrupt:
        pass
    assert stream.getvalue().endswith("\x1b]111\x1b\\")


def test_terminal_background_does_not_write_escape_codes_to_pipes(monkeypatch):
    from help_wanted import theme

    stream = StringIO()
    monkeypatch.setattr("sys.stdout", stream)
    with theme.terminal_background():
        pass
    assert stream.getvalue() == ""


def test_cli_applies_background_for_the_entire_run(monkeypatch):
    from help_wanted import cli

    stream = StringIO()
    monkeypatch.setattr(stream, "isatty", lambda: True)
    monkeypatch.setattr("sys.stdout", stream)
    monkeypatch.setenv("TERM", "xterm-256color")

    def run(*, fresh):
        assert fresh
        assert stream.getvalue() == "\x1b]11;#000000\x1b\\"

    monkeypatch.setattr(cli, "_main", run)
    cli.main(fresh=True)
    assert stream.getvalue().endswith("\x1b]111\x1b\\")


@pytest.mark.parametrize("kind, active_height", [("text", 5), ("select", 7), ("checkbox", 7)])
def test_answer_boxes_are_compact_and_completed_questions_have_one_spacer(kind, active_height):
    async def run():
        with create_pipe_input() as pipe:
            kwargs = dict(qmark="", style=PROMPT_STYLE, input=pipe, output=DummyOutput())
            if kind != "text":
                kwargs.update(choices=["Python", "Skip"], instruction=" ")
            question = boxed_question(getattr(questionary, kind)("", **kwargs), "Your question?")
            heights = []

            def capture(app):
                heights.append(app.layout.container.preferred_height(80, 24).preferred)
                if not app.is_done:
                    pipe.send_text("\r")

            question.application.after_render += capture
            await question.unsafe_ask_async()
            return heights

    heights = asyncio.run(run())
    assert heights[0] == active_height
    # Heading + top border + answer + bottom border + one blank line.
    assert heights[-1] == 5


@pytest.mark.parametrize("width", [40, 80, 100])
def test_title_has_rounded_border_and_fits_terminal(width):
    from help_wanted.theme import TITLE_ART, print_title

    stream = StringIO()
    print_title(Console(file=stream, width=width))
    lines = stream.getvalue().splitlines()
    assert lines[0].startswith("╭") and lines[0].endswith("╮")
    assert any(line.startswith("╰") and line.endswith("╯") for line in lines)
    assert all(len(line) <= width for line in lines)
    if width >= 80:
        assert TITLE_ART.splitlines()[1] in stream.getvalue()
    else:
        assert "HELP WANTED" in stream.getvalue()


def test_title_banner_is_centered_on_a_wide_terminal():
    from help_wanted.theme import TITLE_ART, print_title

    stream = StringIO()
    print_title(Console(file=stream, width=160))
    top_border = stream.getvalue().splitlines()[0]
    assert top_border.index("╭") == 30
    assert top_border.index("╮") == 129
    assert "█" not in TITLE_ART


@pytest.mark.parametrize("keys, cloud", [("\r", False), ("\x1b[B\r", True)])
def test_gemma_choice_uses_themed_keyboard_prompt(monkeypatch, keys, cloud):
    from help_wanted import ollama_setup

    select = questionary.select
    with create_pipe_input() as pipe:
        def make_question(*args, **kwargs):
            return select(*args, **kwargs, input=pipe, output=DummyOutput())

        monkeypatch.setattr(ollama_setup.questionary, "select", make_question)
        pipe.send_text(keys)
        assert ollama_setup._choose_cloud(Console(file=StringIO(), force_terminal=True)) is cloud
