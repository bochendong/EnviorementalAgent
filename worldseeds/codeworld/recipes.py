"""The recipe book of the town theme: which machines each kind of workshop has, and what each machine
turns into what. What a machine does to a good's *grade* (a number 0..100) is its hidden law; the recipe
itself (``oven: dough -> bread``) is public.

Goods come in five levels, from raw materials to finished products. Every machine takes one good and makes
one good of the next level. Several workshops can make the same good (a mill on the farm and a grinder in
the bakery both make flour), each in its own way: that is what has to be learned.
"""

from __future__ import annotations

GOODS_BY_LEVEL = [
    ["wheat", "milk", "ore", "herbs"],
    ["flour", "butter", "iron", "tonic"],
    ["dough", "cheese", "tools", "medicine"],
    ["bread", "pie", "cart", "remedy"],
    ["feast", "hamper", "wagon", "elixir"],
]

# kind of workshop -> [(machine, input, output)], at most 8 (a room has 8 places along its walls)
RECIPES: dict[str, list[tuple[str, str, str]]] = {
    "farm": [("mill", "wheat", "flour"), ("churn", "milk", "butter"), ("herb_rack", "herbs", "tonic"),
             ("cheese_press", "butter", "cheese"), ("feed_trough", "flour", "dough"), ("toolshed", "iron", "tools"),
             ("cart_shed", "tools", "cart"), ("hamper_bench", "pie", "hamper")],
    "bakery": [("grinder", "wheat", "flour"), ("butter_churn", "milk", "butter"), ("kneader", "flour", "dough"),
               ("mixer", "butter", "dough"), ("oven", "dough", "bread"), ("pie_oven", "cheese", "pie"),
               ("pastry_table", "dough", "pie"), ("banquet_table", "bread", "feast")],
    "smithy": [("furnace", "ore", "iron"), ("bloomery", "ore", "iron"), ("forge", "iron", "tools"),
               ("anvil", "iron", "tools"), ("lathe", "tools", "cart"), ("instrument_bench", "tools", "remedy"),
               ("wheelwright", "cart", "wagon"), ("axle_press", "cart", "wagon")],
    "mine": [("smelter", "ore", "iron"), ("crucible", "ore", "iron"), ("ore_washer", "ore", "iron"),
             ("workbench", "iron", "tools"), ("drill_press", "iron", "tools"), ("mine_cart", "tools", "cart"),
             ("rail_shop", "tools", "cart"), ("winch_shop", "cart", "wagon")],
    "clinic": [("herb_press", "herbs", "tonic"), ("mortar", "herbs", "tonic"), ("ointment_mixer", "butter", "medicine"),
               ("still", "tonic", "medicine"), ("decoction_pot", "tonic", "medicine"), ("pill_press", "medicine", "remedy"),
               ("kit_bench", "tools", "remedy"), ("elixir_lab", "remedy", "elixir")],
    "inn": [("dairy", "milk", "butter"), ("kettle", "herbs", "tonic"), ("stove", "flour", "dough"),
            ("hearth_oven", "dough", "bread"), ("cheese_grill", "cheese", "pie"), ("pie_kitchen", "dough", "pie"),
            ("feast_table", "pie", "feast"), ("banquet_hall", "bread", "feast")],
    "shop": [("sack_filler", "wheat", "flour"), ("tonic_bottler", "herbs", "tonic"), ("cart_counter", "tools", "cart"),
             ("remedy_shelf", "medicine", "remedy"), ("hamper_packer", "bread", "hamper"),
             ("gift_wrapper", "pie", "hamper"), ("wagon_dealer", "cart", "wagon"), ("elixir_counter", "remedy", "elixir")],
    "florist": [("seed_mill", "wheat", "flour"), ("drying_rack", "herbs", "tonic"), ("flower_press", "herbs", "tonic"),
                ("infuser", "tonic", "medicine"), ("balm_mixer", "butter", "medicine"),
                ("potpourri_table", "medicine", "remedy"), ("posy_bench", "remedy", "hamper"), ("perfumery", "remedy", "elixir")],
}

# what each machine looks like on the map
LOOK = {
    "mill": "mill", "grinder": "mill", "sack_filler": "mill", "seed_mill": "mill",
    "churn": "churn", "butter_churn": "churn", "dairy": "churn",
    "herb_rack": "rack", "drying_rack": "rack", "flower_press": "press",
    "cheese_press": "press", "herb_press": "press", "pill_press": "press", "axle_press": "press",
    "oven": "oven", "pie_oven": "oven", "hearth_oven": "oven", "cheese_grill": "oven", "stove": "oven",
    "furnace": "furnace", "bloomery": "furnace", "smelter": "furnace", "crucible": "furnace", "ore_washer": "furnace",
    "forge": "anvil", "anvil": "anvil", "workbench": "anvil", "drill_press": "anvil", "lathe": "anvil",
    "instrument_bench": "anvil", "kit_bench": "anvil", "toolshed": "anvil",
    "cart_shed": "cart", "mine_cart": "cart", "rail_shop": "cart", "winch_shop": "cart", "wheelwright": "cart",
    "wagon_dealer": "cart", "cart_counter": "cart",
    "still": "still", "decoction_pot": "still", "kettle": "still", "tonic_bottler": "still", "infuser": "still",
    "elixir_lab": "still", "perfumery": "still", "mortar": "still", "ointment_mixer": "still", "balm_mixer": "still",
    "remedy_shelf": "shelf", "elixir_counter": "shelf",
}
# everything else (kneader, mixer, tables, benches, packers) is a work table
for _ms in RECIPES.values():
    for _m, _, _ in _ms:
        LOOK.setdefault(_m, "table")


def title(machine: str) -> str:
    """``pie_oven`` -> ``Pie oven``."""
    return machine.replace("_", " ").capitalize()
