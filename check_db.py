import sqlite3
conn = sqlite3.connect('D:/VST_PROJECTS/IMS_VST/V2_vst/backend/vst_ims.db')
cursor = conn.cursor()
cursor.execute('SELECT category, criticality_score, COUNT(*) as cnt FROM products GROUP BY category, criticality_score ORDER BY category, criticality_score')
rows = cursor.fetchall()
print('Categories and criticality_scores:')
for row in rows:
    print(row)
print()
cursor.execute('SELECT COUNT(*) FROM products')
print('Total products:', cursor.fetchone()[0])
conn.close()