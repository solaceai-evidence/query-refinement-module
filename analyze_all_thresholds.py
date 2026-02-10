import sqlite3

db_path = "query_refinement.db"
conn = sqlite3.connect(db_path)
cursor = conn.cursor()

# Analyze across ALL sessions, not just 790
query = """
SELECT 
    rs.aspect_name,
    COUNT(fh.id) as followup_count,
    rs.query_id
FROM refinement_steps rs
LEFT JOIN followup_history fh ON rs.id = fh.refinement_step_id
GROUP BY rs.query_id, rs.aspect_name
ORDER BY followup_count DESC;
"""

cursor.execute(query)
results = cursor.fetchall()

print("Analyzing ALL sessions in database:")
print("=" * 60)

turn_distribution = {1: 0, 2: 0, 3: 0, 4: 0, 5: 0, 6: 0}
examples_per_category = {1: [], 2: [], 3: [], 4: [], 5: [], 6: []}

for aspect_name, followup_count, query_id in results:
    turns = followup_count + 1  # followups + initial turn
    
    if turns >= 6:
        turn_distribution[6] += 1
        if len(examples_per_category[6]) < 3:
            examples_per_category[6].append((aspect_name, turns, query_id))
    elif turns == 5:
        turn_distribution[5] += 1
        if len(examples_per_category[5]) < 3:
            examples_per_category[5].append((aspect_name, turns, query_id))
    elif turns == 4:
        turn_distribution[4] += 1
        if len(examples_per_category[4]) < 3:
            examples_per_category[4].append((aspect_name, turns, query_id))
    elif turns == 3:
        turn_distribution[3] += 1
        if len(examples_per_category[3]) < 3:
            examples_per_category[3].append((aspect_name, turns, query_id))
    elif turns == 2:
        turn_distribution[2] += 1
    else:
        turn_distribution[1] += 1

total_dims = sum(turn_distribution.values())
print(f"Total dimensions analyzed: {total_dims}")
print("\nTurn distribution:")
for turns in range(1, 7):
    count = turn_distribution[turns]
    pct = count / total_dims * 100
    label = f"{turns} turn{'s' if turns > 1 else ''}"
    print(f"  {label:10s}: {count:4d} dimensions ({pct:5.1f}%)")
    
    if examples_per_category[turns]:
        for aspect_name, t, qid in examples_per_category[turns][:2]:
            print(f"              └─ {aspect_name} (query {qid})")

print("\n" + "=" * 60)
print("THRESHOLD COMPARISON:")
print("=" * 60)

for threshold in [2, 3, 4, 5]:
    affected_dims = sum(turn_distribution[t] for t in range(threshold, 7))
    pct = affected_dims / total_dims * 100
    
    # Estimate cost impact
    # Assume each affected dimension triggers reinforcement for all turns >= threshold
    # For simplicity, assume 1 reinforcement per affected dimension
    tokens_added = affected_dims * 3000  # ~3,000 tokens per reinforcement
    baseline_tokens = total_dims * 3000  # Rough baseline per dimension
    cost_increase_pct = tokens_added / baseline_tokens * 100
    
    print(f"\nThreshold = {threshold}:")
    print(f"  Dimensions affected: {affected_dims:4d} ({pct:5.1f}%)")
    print(f"  Extra tokens:        {tokens_added:,} tokens")
    print(f"  Cost increase:       ~{cost_increase_pct:.1f}%")
    
    # Quality consideration
    if threshold == 2:
        print(f"  Quality impact:      Catches issues EARLY, but higher cost")
    elif threshold == 3:
        print(f"  Quality impact:      Balanced - catches most issues after one failed turn")
    elif threshold == 4:
        print(f"  Quality impact:      More selective - only persistent issues")
    elif threshold == 5:
        print(f"  Quality impact:      Very selective - only extreme cases")

print("\n" + "=" * 60)
print("RECOMMENDATION ANALYSIS:")
print("=" * 60)

dims_2plus = sum(turn_distribution[t] for t in range(2, 7))
dims_3plus = sum(turn_distribution[t] for t in range(3, 7))
dims_4plus = sum(turn_distribution[t] for t in range(4, 7))

print(f"\nDimensions completing in 1 turn: {turn_distribution[1]} ({turn_distribution[1]/total_dims*100:.1f}%)")
print(f"  → No improvement needed, already perfect")

print(f"\nDimensions needing 2+ turns: {dims_2plus} ({dims_2plus/total_dims*100:.1f}%)")
print(f"  → Threshold=2 would help all of these")
print(f"  → But 2-turn conversations are often normal refinement")

print(f"\nDimensions needing 3+ turns: {dims_3plus} ({dims_3plus/total_dims*100:.1f}%)")
print(f"  → Threshold=3 targets THIS group")
print(f"  → By turn 3, instruction drift likely occurring")
print(f"  → Good balance: not too aggressive, not too late")

print(f"\nDimensions needing 4+ turns: {dims_4plus} ({dims_4plus/total_dims*100:.1f}%)")
print(f"  → Threshold=4 only helps persistent problems")
print(f"  → May be too late - drift already occurred at turn 3")

conn.close()
