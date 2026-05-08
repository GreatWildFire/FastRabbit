import json

def get_shot_brief(shot_id):
    # 解析S01_SH01 -> ep01/scene_S01
    scene_part = "_".join(shot_id.split("_")[:2])  # S01
    ep = "ep_01"  # 先写死
    brief_path = f"project/assets/shots/{shot_id}/brief.json"
    with open(brief_path) as f:
        return json.load(f)

brief = get_shot_brief("S01_SH01")
print("场景图:", brief["scene_ref"])
for char in brief["character_refs"]:
    print(f"角色 {char['char_id']}: {char['image']}")