"""Shared terminal palette and rounded questionnaire layout."""

from contextlib import contextmanager
import os
import sys

from prompt_toolkit.layout import HSplit, Layout, VSplit, Window
from prompt_toolkit.layout.controls import FormattedTextControl
from prompt_toolkit.layout.dimension import Dimension
from prompt_toolkit.filters import is_done
from prompt_toolkit.output import ColorDepth
from questionary import Style
from questionary.prompts.common import InquirerControl
from rich.console import Console, Group
from rich import box
from rich.align import Align
from rich.panel import Panel
from rich.text import Text
from rich.theme import Theme

ORANGE = "#ff8700"
TITLE_ART = r""" _   _      _       __        __          _           _
| | | | ___| |_ __  \ \      / /_ _ _ __ | |_ ___  __| |
| |_| |/ _ \ | '_ \  \ \ /\ / / _` | '_ \| __/ _ \/ _` |
|  _  |  __/ | |_) |  \ V  V / (_| | | | | ||  __/ (_| |
|_| |_|\___|_| .__/    \_/\_/ \__,_|_| |_|\__\___|\__,_|
             |_|"""


def print_title(console: Console) -> None:
    """Center the banner, falling back to a small title on narrow terminals."""
    # Body output is limited to 100 columns, but the banner uses the full terminal.
    terminal_width = Console(file=console.file).width if console.is_terminal else console.width
    banner_console = Console(
        file=console.file, width=terminal_width, color_system=console.color_system,
        force_terminal=console.is_terminal, style="#ffffff on #000000",
    )
    panel_width = min(100, terminal_width)
    title = TITLE_ART if panel_width >= max(map(len, TITLE_ART.splitlines())) + 6 else "HELP WANTED"
    banner_console.print(Align.center(Panel(
        Group(
            Align.center(Text(title)),
            Text(""),
            Align.center(Text("Find your first open-source contribution.")),
        ),
        box=box.ROUNDED, border_style=ORANGE, padding=(1, 2), width=panel_width,
    )))
    console.print()


@contextmanager
def terminal_background():
    """Color unpainted terminal cells too; reset to its configured color on exit.

    OSC 11 changes the default background, unlike text styling, which only
    covers printed cells. OSC 111 restores the terminal's configured default.
    Terminals without dynamic-color support may ignore these sequences.
    """
    stream = sys.stdout
    enabled = stream.isatty() and os.environ.get("TERM") != "dumb"
    if enabled:
        stream.write("\x1b]11;#000000\x1b\\")
        stream.flush()
    try:
        yield
    finally:
        if enabled:
            stream.write("\x1b]111\x1b\\")
            stream.flush()


PROMPT_STYLE = Style([
    ("", "fg:#ffffff bg:#000000"),
    ("question", "fg:#ffffff bold"),
    ("qmark", f"fg:{ORANGE} bold"),
    ("answer", "fg:#ffffff"),
    ("pointer", f"fg:{ORANGE} bold"),
    ("highlighted", f"fg:{ORANGE} bold"),
    ("selected", f"fg:{ORANGE}"),
    ("instruction", "fg:#ffffff"),
    ("text", "fg:#ffffff"),
    ("border", f"fg:{ORANGE} bg:#000000"),
    ("surface", "fg:#ffffff bg:#000000"),
    ("bottom-toolbar", "fg:#ffffff bg:#000000"),
])


def themed_console() -> Console:
    return Console(style="#ffffff on #000000", width=min(100, Console().width),
                   color_system="truecolor" if Console().is_terminal else None, theme=Theme({
        "accent": f"{ORANGE} on #000000",
        "markdown.h1": f"bold {ORANGE} on #000000",
        "markdown.h2": f"bold {ORANGE} on #000000",
        "markdown.link": f"{ORANGE} on #000000",
        "markdown.link_url": f"{ORANGE} on #000000",
    }))


def boxed_question(question, message: str):
    """Keep Questionary's input handling, framing its layout below a heading."""
    def corner(character):
        return Window(width=1, height=1, char=character, style="class:border")

    def edge(left, right):
        return VSplit([
            corner(left),
            Window(height=1, char="─", style="class:border"),
            corner(right),
        ], height=1)

    original = question.application.layout
    choices = next((control for control in original.find_all_controls()
                    if isinstance(control, InquirerControl)), None)

    def answer_height():
        if choices is None or is_done():
            return 1
        # One header row is owned by Questionary; the rest are the choices.
        return min(len(choices.choices) + 1, 12)

    # Palette-based black can be remapped by the Contributor's terminal theme.
    question.application._color_depth = ColorDepth.DEPTH_24_BIT
    box = HSplit([
        edge("╭", "╮"),
        VSplit([
            Window(width=1, char="│", style="class:border"),
            HSplit([original.container], height=answer_height),
            Window(width=1, char="│", style="class:border"),
        ]),
        edge("╰", "╯"),
    ])
    content = HSplit([
        Window(FormattedTextControl([
            ("class:qmark", " # "),
            ("class:question", " ".join(message.split())),
        ]), height=1, wrap_lines=False),
        box,
        Window(height=1),
    ], width=Dimension(max=100), style="class:surface")
    question.application.layout = Layout(
        content, focused_element=original.current_control,
    )
    return question
