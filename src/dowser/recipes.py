"""Guided searches: the questions to ask, in order, for one particular cheat.

A raw search asks you to know that money is three bytes of BCD, that Pokémon
stores HP big-endian, and that two rounds of "equals" is the fastest way to pin
an encounter. A recipe knows all of that, and asks you instead what your money
says and whether you just spent some.

Each recipe is a list of steps. A step is a sentence to show, the filter to run,
and what kind of answer it needs — a number, a species, an item, or nothing at
all. That's enough for an interface to build itself, and it keeps the knowledge
about each game in data rather than scattered through the view.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from . import scan

#: What a step needs from the person running it.
#: none — just press the button; number — type a figure; species/item — pick one.
Answer = str


@dataclass(frozen=True)
class Step:
    prompt: str
    filter: str
    answer: Answer = "none"
    hint: str = ""


@dataclass(frozen=True)
class Recipe:
    id: str
    name: str
    blurb: str
    width: str
    steps: list[Step]
    #: What the value you write means, so the picker matches the search.
    applies: Answer = "number"
    #: Shown once the address is found.
    apply_hint: str = ""
    #: Honest warning where one is owed.
    caution: str = ""
    #: True when applying this cheat destroys the variation the search needs,
    #: so the address has to be remembered or it is gone for this save.
    self_erasing: bool = False
    tags: list[str] = field(default_factory=list)


ASK = {
    "equals": (scan.equals, 1),
    "decreased": (scan.decreased, 0),
    "increased": (scan.increased, 0),
    "changed": (scan.changed, 0),
    "unchanged": (scan.unchanged, 0),
    "decreased-by": (scan.decreased_by, 1),
    "increased-by": (scan.increased_by, 1),
}


RECIPES: list[Recipe] = [
    Recipe(
        id="wild-species",
        name="Choose which Pokémon appears",
        blurb="Force every wild encounter to be one species. This is the Mew one.",
        width="u8",
        applies="species",
        tags=["encounters"],
        steps=[
            Step(
                "Walk into grass. What appeared?",
                "equals",
                "species",
                "Any wild Pokémon. Its name is on screen.",
            ),
            Step(
                "Run away and find a different one. What is it?",
                "equals",
                "species",
                "It has to be a different species, or the round tells us nothing.",
            ),
            Step(
                "Once more, a third species.",
                "equals",
                "species",
                "Skip this if you're already down to a handful.",
            ),
        ],
        apply_hint=(
            "Several addresses hold the species at once and only one drives the generator. "
            "Hold them all, walk into grass, and see whether it took."
        ),
        self_erasing=True,
    ),
    Recipe(
        id="encounter-level",
        name="Set the level of wild Pokémon",
        blurb="Every wild Pokémon you meet appears at the level you choose.",
        width="u8",
        tags=["encounters"],
        steps=[
            Step("Get into a wild battle. What level is it?", "equals", "number"),
            Step("Find another at a different level. What level?", "equals", "number"),
            Step("And once more.", "equals", "number"),
        ],
        caution="Very high levels can give a Pokémon moves the game doesn't expect. 100 is safe.",
        self_erasing=True,
    ),
    Recipe(
        id="money",
        name="Set your money",
        blurb="Change the ¥ on your trainer card to anything up to 999,999.",
        width="bcd3",
        tags=["resources"],
        steps=[
            Step("How much money do you have?", "equals", "number", "Exactly, digits only."),
            Step("Buy or sell something, then press this.", "changed"),
            Step("How much now?", "equals", "number"),
        ],
        apply_hint="999999 is the most the game will show.",
    ),
    Recipe(
        id="item-quantity",
        name="Set how many of an item you have",
        blurb="Pick a bag slot and hold its count at 99, so it never runs out.",
        width="u8",
        tags=["items"],
        steps=[
            Step(
                "Open your bag. How many of the item do you have?",
                "equals",
                "number",
                "Pick something you can use or toss, like a Potion.",
            ),
            Step("Use or toss one, then press this.", "decreased-by", "number", "How many went?"),
            Step("How many are left?", "equals", "number"),
        ],
        apply_hint="99 is the cap the game enforces.",
    ),
    Recipe(
        id="item-slot",
        name="Turn a bag item into another item",
        blurb="Change what an item in your bag actually is. This is how you get Master Balls.",
        width="u8",
        applies="item",
        tags=["items"],
        steps=[
            Step(
                "What item is in the slot you want to change?",
                "equals",
                "item",
                "Its ID, not how many you have. Pick from the list.",
            ),
            Step(
                "Move it to a different position in the bag, then press this.",
                "changed",
                hint="Bag → the item → Move.",
            ),
            Step("Put it back, then say what's in that slot now.", "equals", "item"),
        ],
        caution=(
            "Writing an item number the game doesn't use can lock up the bag. Save state first."
        ),
    ),
    Recipe(
        id="pp",
        name="Stop a move running out of PP",
        blurb="Hold one move's PP full so you can use it forever.",
        width="u8",
        tags=["battle"],
        steps=[
            Step("In a battle, what's the PP of the move you'll use?", "equals", "number"),
            Step("Use it once, then press this.", "decreased-by", "number", "Usually 1."),
            Step("What's the PP now?", "equals", "number"),
        ],
    ),
    Recipe(
        id="stats",
        name="Change a Pokémon's stats",
        blurb="Set Attack, Defence, Speed or max HP on the Pokémon in your party.",
        width="u16be",
        tags=["party"],
        steps=[
            Step(
                "Look at the stat in the party screen. What is it?",
                "equals",
                "number",
                "Pokémon stores these high byte first, which is why a plain search misses them.",
            ),
            Step("Switch to a different Pokémon in the party, then press this.", "changed"),
            Step("Switch back. What's the stat again?", "equals", "number"),
        ],
    ),
    Recipe(
        id="experience",
        name="Set a Pokémon's experience",
        blurb="Put a Pokémon just under a level-up, or a long way past one.",
        width="u24be",
        tags=["party"],
        steps=[
            Step("What's the Pokémon's EXP total?", "equals", "number", "Party screen, page two."),
            Step("Win a battle, then press this.", "increased"),
            Step("What's the EXP now?", "equals", "number"),
        ],
        caution="Levels only recalculate when the Pokémon next gains EXP or is revived.",
    ),
    Recipe(
        id="steps",
        name="Turn wild battles off (or on)",
        blurb="Walk through grass undisturbed, or trigger an encounter on every single step.",
        width="u8",
        tags=["encounters"],
        steps=[
            Step("Stand still in grass and press this.", "unchanged"),
            Step("Take a few steps, then press this.", "decreased"),
            Step("A few more steps.", "decreased"),
            Step("Stand still again.", "unchanged"),
        ],
        apply_hint="Hold it at 255 to be left alone, or 1 for an encounter every step.",
    ),
    Recipe(
        id="catch-rate",
        name="Make anything easy to catch",
        blurb="Hold the hidden catch value at maximum so almost any Ball works.",
        width="u8",
        tags=["battle"],
        steps=[
            Step(
                "Get into a battle with something hard to catch, then press this.",
                "unchanged",
                hint="You can't see this number, so the search works by elimination.",
            ),
            Step("Run, and battle something easy to catch instead.", "changed"),
            Step("Run, and battle the hard one again.", "changed"),
            Step("Stay in the battle and press this.", "unchanged"),
        ],
        apply_hint="255 is the easiest to catch.",
        caution="This one is genuinely fiddly — expect to need a few extra rounds.",
    ),
    Recipe(
        id="shiny",
        name="Make wild Pokémon shiny",
        blurb="Force the hidden values that decide whether a wild Pokémon sparkles.",
        width="u16be",
        tags=["encounters"],
        steps=[
            Step(
                "In a wild battle, press this.",
                "unchanged",
                hint="DVs aren't shown anywhere, so this is an elimination search too.",
            ),
            Step("Run and meet a different wild Pokémon.", "changed"),
            Step("Stay in that battle and press this.", "unchanged"),
            Step("Run and meet another.", "changed"),
        ],
        apply_hint=(
            "In Gold and Silver a Pokémon is shiny when its Speed, Defence and Special DVs are "
            "all 10 and its Attack DV is 2, 3, 6, 7, 10, 11, 14 or 15. Holding the DV pair at "
            "43690 sets every DV to 10, which qualifies and gives good stats too."
        ),
        caution="DVs also set stats, so a shiny made this way will have unusual numbers.",
    ),
]

BY_ID = {recipe.id: recipe for recipe in RECIPES}
