import sqlite3

db_path = "query_refinement.db"
conn = sqlite3.connect(db_path)
cursor = conn.cursor()

# Count followups per dimension for session 790
query = """
SELECT 
    rs.aspect_name,
    COUNT(fh.id) as followup_count
FROM refinement_steps rs
LEFT JOIN followup_history fh ON rs.id = fh.refinement_step_id
WHERE rs.query_id IN (SELECT id FROM queries WHERE session_id = 790)
GROUP BY rs.aspect_name
ORDER BY followup_count DESC;
"""

cursor.execute(query)
results = cursor.fetchall()

print("Followup counts per dimension (session 790):")
print("=" * 60)

turn_distribution = {0: 0, 1: 0, 2: 0, 3: 0, 4: 0, 5: 0}
for aspect_name, followup_count in results:
    # followup_count = number of followups, so turns = followups + 1 (initial)
    turns = followup_count + 1
    if turns >= 5:
        turn_distribution[5] += 1
    elif turns == 4:
        turn_distribution[4] += 1
    elif turns == 3:
        turn_distribution[3] += 1
    elif turns == 2:
        turn_distribution[2] += 1
    else:
        turn_distribution[1] += 1
    
    if turns >= 3:
        print(f"{aspect_name}: {turns} turns")

print("\n" + "=" * 60)
print("Turn distribution summary:")
print(f"  1 turn:  {turn_distribution[1]} dimensions")
print(f"  2 turns: {turn_distribution[2]} dimensions")
print(f"  3 turns: {turn_distribution[3]} dimensions")
print(f"  4 turns: {turn_distribution[4]} dimensions")
print(f"  5+ turns: {turn_distribution[5]} dimensions")

total_dims = sum(turn_distribution.values())
dims_3plus = turn_distribution[3] + turn_distribution[4] + turn_distribution[5]
dims_4plus = turn_distribution[4] + turn_distribution[5]
dims_5plus = turn_distribution[5]

print(f"\nThreshold analysis:")
print(f"  Total dimensions: {total_dims}")
print(f"  Would trigger at threshold=3: {dims_3plus} dims ({dims_3plus/total_dims*100:.1f}%)")
print(f"  Would trigger at threshold=4: {dims_4plus} dims ({dims_4plus/total_dims*100:.1f}%)")
print(f"  Would trigger at threshold=5: {dims_5plus} dims ({dims_5plus/total_dims*100:.1f}%)")

print(f"\nCost analysis (based on ~3,000 token reinforcement):")
print(f"  Threshold=3: Adds {dims_3plus * 3000} tokens total")
print(f"  Threshold=4: Adds {dims_4plus * 3000} tokens total") 
print(f"  Threshold=5: Adds {dims_5plus * 3000} tokens total")

conn.close()
