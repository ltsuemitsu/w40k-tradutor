#!/usr/bin/env python3
"""Mark common-English polysemes as inline:false (exact EN still works)."""
import json
import shutil
from datetime import datetime
from pathlib import Path

# Common English / high-polysemy singles — keep EXACT preserve, disable INLINE lock.
# Unique 40k terms (Psyker, Bolter, Commissar, Fenris, …) stay default inline:true.
SOFT_INLINE_FALSE = {
    # top false-positive drivers from dry-run
    "Command", "Charge", "Shield", "Sword", "Warrior", "Officer", "Noble",
    "Loyalty", "Sacrifice", "Soldier", "Catch", "Flash", "Contempt", "Furious",
    "Knife", "Fortune", "Raid", "Endure", "Discipline", "Integrity", "Cleansing",
    "Split", "Destined", "Intervention", "Anticipation", "Carnage", "Dash",
    "Onslaught", "Revenge", "March", "Ambush", "Elite", "Axe", "Kick", "Distract",
    "Mutation", "Fortress", "Guidance", "Inspire", "Rear", "Vigilance", "Tyrant",
    "Aggressive", "Slash", "Defender", "Ignite", "Survivor", "Artificial",
    "Stabilise", "Stabilize", "Withdraw", "Destroyer", "Bloodlust", "Disarray",
    "Salvation", "Overseer", "Assassin", "Executioner", "Operative", "Vanguard",
    # more short verbs/nouns that are talent names but English words
    "Strike", "Attack", "Defend", "Block", "Parry", "Dodge", "Aim", "Focus",
    "Power", "Force", "Will", "Faith", "Fear", "Hate", "Rage", "Fury",
    "Blood", "Death", "Life", "Pain", "Wound", "Kill", "Hunt", "Prey",
    "Guard", "Cover", "Hold", "Push", "Pull", "Break", "Crush", "Smash",
    "Burn", "Freeze", "Shock", "Blast", "Burst", "Shot", "Fire", "Flame",
    "Light", "Dark", "Shadow", "Storm", "Thunder", "Lightning",
    "Master", "Servant", "Leader", "Follower", "Enemy", "Ally", "Friend",
    "Hero", "Beast", "Monster", "Demon", "Daemon", "Angel",
    "Saint", "Sinner", "Martyr", "Martyrdom", "Zealot", "Heretic",
    "Order", "Chaos", "Law", "Crime", "Justice", "Judgement", "Judgment",
    "Truth", "Lie", "Secret", "Knowledge", "Wisdom", "Ignorance",
    "Strength", "Weakness", "Speed", "Agility", "Toughness", "Resilience",
    "Awareness", "Perception", "Intelligence", "Fellowship", "Charisma",
    "Commerce", "Trade", "Bargain", "Deal", "Debt", "Profit",
    "Duty", "Honor", "Honour", "Glory", "Shame", "Pride",
    "Hope", "Despair", "Courage", "Cowardice", "Resolve", "Doubt",
    "Mercy", "Cruelty", "Grace", "Wrath", "Vengeance",
    "Advance", "Retreat", "Flee", "Chase", "Escape", "Capture",
    "Search", "Hide", "Reveal", "Expose", "Conceal",
    "Build", "Destroy", "Create", "Repair", "Restore",
    "Learn", "Teach", "Train", "Study", "Practice",
    "Wait", "Rest", "Sleep", "Wake", "Watch", "Listen",
    "Speak", "Silence", "Voice", "Word", "Name", "Title",
    "Path", "Way", "Road", "Gate", "Door", "Wall", "Bridge",
    "Crown", "Throne", "Empire", "Kingdom", "Domain",
    "War", "Peace", "Battle", "Fight", "Duel", "Conflict",
    "Victory", "Defeat", "Triumph", "Failure", "Success",
    "Gift", "Curse", "Blessing", "Boon", "Bane",
    "Mark", "Sign", "Symbol", "Token", "Seal",
    "Chain", "Bond", "Link", "Tie", "Bind",
    "Rise", "Fall", "Climb", "Drop", "Lift",
    "Open", "Close", "Lock", "Unlock",
    "Begin", "End", "Start", "Stop", "Finish",
    "First", "Last", "Next", "Final", "Ultimate",
    "Great", "Grand", "Lesser", "Greater", "Superior",
    "Ancient", "Eternal", "Mortal", "Immortal", "Undying",
    "Pure", "Tainted", "Corrupted", "Blessed", "Cursed",
    "Sacred", "Profane", "Holy", "Unholy", "Divine",
    "Steel", "Iron", "Gold", "Silver", "Bronze", "Bone",
    "Flesh", "Soul", "Spirit", "Mind",
    "Eye", "Hand", "Heart", "Head", "Face", "Body",
    "Night", "Day", "Dawn", "Dusk", "Midnight",
    "Void", "Star", "Sun", "Moon", "World", "Planet",
    "Ship", "Fleet", "Crew", "Captain", "Pilot",
    "Gun", "Blade", "Hammer", "Spear", "Bow", "Staff",
    "Armor", "Armour", "Helmet", "Boots", "Cloak", "Gloves",
    "Ring", "Amulet", "Charm", "Relic", "Artifact", "Artefact",
    "Potion", "Toxin", "Poison", "Drug", "Medicine",
    "Scroll", "Book", "Tome", "Map", "Chart",
    "Key", "Code", "Cipher", "Signal", "Message",
    "Trap", "Snare", "Mine", "Bomb", "Grenade",
    "Machine", "Engine", "Device", "Tool",
    "Animal", "Bird", "Fish", "Insect",
    "Child", "Children", "Father", "Mother", "Brother", "Sister",
    "King", "Queen", "Prince", "Lord", "Lady", "Knight",
    "Priest", "Monk", "Nun", "Bishop", "Cardinal",
    "Slave", "Owner", "Citizen",
    "Crowd", "Mob", "Gang", "Cult", "Sect", "Church",
    "Temple", "Shrine", "Altar", "Chapel", "Cathedral",
    "Prison", "Cage", "Cell", "Dungeon", "Vault",
    "Market", "Shop", "Store", "Bank",
    "Farm", "Field", "Forest", "Mountain", "River", "Sea", "Ocean",
    "City", "Town", "Village", "Hive", "Colony", "Station",
    "Base", "Camp", "Fort", "Outpost", "Bunker",
    "Room", "Hall", "Chamber", "Corridor", "Passage",
    "Floor", "Ceiling", "Roof", "Ground",
    "Window", "Mirror", "Glass", "Crystal", "Stone",
    "Dust", "Ash", "Smoke", "Fog", "Mist", "Rain", "Snow",
    "Wind", "Air", "Water", "Earth", "Ice",
    "Acid", "Oil", "Fuel", "Gas", "Plasma",
    "Laser", "Bolt", "Shell", "Bullet", "Round", "Ammo",
    "Target", "Scope", "Sight",
    "Concealment", "Stealth",
    "Scout", "Spy", "Agent",
    "Rearguard", "Flank", "Front", "Center", "Centre",
    "Formation", "Rank", "File", "Line", "Column",
    "Report", "Briefing",
    "Mission", "Quest", "Task", "Job",
    "Reward", "Penalty", "Fine", "Tax", "Tribute",
    "Treaty", "Alliance", "Pact", "Truce",
    "Rebellion", "Revolt", "Uprising", "Mutiny", "Coup",
    "Trial", "Test", "Ordeal", "Challenge", "Contest",
    "Game", "Play", "Sport", "Race",
    "Song", "Dance", "Music", "Art", "Craft",
    "Science", "Tech", "Technology", "Research",
    "History", "Legend", "Myth", "Story", "Tale",
    "Dream", "Nightmare", "Vision", "Omen", "Prophecy",
    "Magic", "Spell", "Ritual", "Rite", "Ceremony",
    "Prayer", "Chant", "Hymn", "Psalm", "Litany",
    "Banner", "Flag", "Standard", "Emblem", "Crest",
    "Medal", "Trophy", "Prize", "Award",
    "Grade", "Level", "Tier", "Class",
    "Role", "Profession",
    "Skill", "Talent", "Ability",
    "Trait", "Flaw", "Virtue", "Vice", "Sin",
    "Fate", "Destiny", "Chance", "Luck",
    "Time", "Hour", "Year", "Age", "Era",
    "Past", "Present", "Future", "Eternity", "Moment",
    "Space", "Place", "Location", "Position", "Spot",
    "Direction", "North", "South", "East", "West",
    "Distance", "Range", "Reach", "Span", "Gap",
    "Size", "Scale", "Mass", "Weight", "Height", "Width",
    "Number", "Count", "Amount", "Quantity", "Sum",
    "Value", "Worth", "Price", "Cost", "Fee",
    "Quality", "Condition", "State", "Status",
    "Effect", "Result", "Outcome", "Impact", "Consequence",
    "Cause", "Reason", "Motive", "Purpose", "Goal",
    "Plan", "Scheme", "Plot", "Strategy", "Tactic",
    "Method", "Means", "Manner", "Style",
    "Rule", "Norm", "Custom",
    "Right", "Wrong", "Good", "Evil", "Neutral",
    "True", "False", "Real", "Fake",
    "Here", "There", "Everywhere", "Nowhere", "Somewhere",
    "Now", "Then", "Soon", "Later", "Before", "After",
    "With", "Without", "Within", "Beyond", "Among",
    "Furious", "Contempt", "Destined", "Cleansing",
    "Intervention", "Anticipation", "Integrity", "Discipline",
    "Salvation", "Fortune", "Endure", "Inspire", "Distract",
}


def main():
    root = Path(__file__).resolve().parent.parent
    path = root / "glossary.json"
    bak = path.with_name(
        f"glossary.json.{datetime.now().strftime('%Y%m%d_%H%M%S')}.backup.json"
    )
    shutil.copy2(path, bak)
    print(f"backup -> {bak.name}")

    data = json.loads(path.read_text(encoding="utf-8"))
    terms = data.get("terms", [])
    soft_lower = {s.lower() for s in SOFT_INLINE_FALSE}

    changed = 0
    already = 0
    for t in terms:
        en = (t.get("term_english") or "").strip()
        if en.lower() not in soft_lower:
            continue
        if t.get("inline") is False:
            already += 1
            continue
        t["inline"] = False
        if "preserve" not in t:
            t["preserve"] = True
        changed += 1

    present = {(t.get("term_english") or "").strip().lower() for t in terms}
    missing = sorted(soft_lower - present)

    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"marked inline=false: {changed}")
    print(f"already false: {already}")
    print(f"soft list size: {len(soft_lower)} | not in glossary: {len(missing)}")


if __name__ == "__main__":
    main()
