"""Generate journal map-marker definitions (one .lsx per marker) for LootAdvisor.

Same format as the game's own markers in Gustav.pak: Mods/GustavDev/Story/Journal/Markers/<Guid>.lsx
(542 vanilla markers; MarkerTargetObjectType Item/Character/Trigger; MarkerIcon QuestMarker/LocationMarker/
SecretMarker). Vanilla example for an item: MarkerID "LOW_Elfsong_EmperorSword", target = the level placement
MapKey 5e46d5b5-0a24-4e01-adc9-96914091cdbe in CTY_Main_A.

Input: rows of {id, target, target_type, level, handle, icon}. `target` = instance MapKey from
LootAdvisor/data/cache/level_items_index.json (the item itself, or its container / NPC holder).
`handle` = a new DisplayText loca handle; the mod writes its text at runtime (Ext.Loca.UpdateTranslatedString).

  python gen_markers.py              -> writes the spike's two test markers
"""
import os
import uuid

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "Mods", "LootAdvisorSpike", "Story", "Journal", "Markers")

TEMPLATE = """<?xml version="1.0" encoding="UTF-8"?>
<save>
    <version major="4" minor="0" revision="9" build="319"/>
    <region id="Markers">
        <node id="root">
            <children>
                <node id="Marker">
                    <attribute id="DisplayText" type="TranslatedString" handle="{handle}" version="1"/>
                    <attribute id="Guid" type="guid" value="{guid}"/>
                    <attribute id="MarkerID" type="FixedString" value="{id}"/>
                    <attribute id="MarkerIcon" type="FixedString" value="{icon}"/>
                    <attribute id="MarkerLevel" type="FixedString" value="{level}"/>
                    <attribute id="MarkerTargetObjectType" type="FixedString" value="{target_type}"/>
                    <attribute id="MarkerTargetObjectUUID" type="FixedString" value="{target}"/>
                    <attribute id="Radius" type="int32" value="0"/>
                </node>
            </children>
        </node>
    </region>
</save>
"""

# Stable GUID per MarkerID so regenerating does not create new markers
NS = uuid.UUID("2e3407b4-e6ef-4cf7-9de7-25950e9f82f9")

SPIKE = [
    dict(id="LAS_Test_EmperorSword", target="5e46d5b5-0a24-4e01-adc9-96914091cdbe", target_type="Item",
         level="CTY_Main_A", handle="h9d449e77g92a5g44f8g893eg9e8418117600", icon="QuestMarker"),
    dict(id="LAS_Test_PhalarAluve", target="cc16c1cb-d355-47df-820a-33a83c42234b", target_type="Item",
         level="WLD_Main_A", handle="heb5c33a4g63efg4452ga7bbg0d9a8e1b2389", icon="SecretMarker"),
]


def write(rows, out=OUT):
    os.makedirs(out, exist_ok=True)
    for r in rows:
        guid = str(uuid.uuid5(NS, r["id"]))
        with open(os.path.join(out, guid + ".lsx"), "w", encoding="utf-8", newline="\n") as f:
            f.write(TEMPLATE.format(guid=guid, **r))
    return len(rows)


if __name__ == "__main__":
    print("wrote", write(SPIKE), "markers to", OUT)
