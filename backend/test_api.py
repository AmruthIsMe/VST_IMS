from app.database import get_db
from app.routers.products import list_products
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)
resp = client.get('/api/products?page_size=500')
print('Status:', resp.status_code)
data = resp.json()
print('Total products (no filter):', data['total'])
print('Items count:', len(data['items']))
if data['items']:
    print('First item category:', data['items'][0].get('category'))
    print('First item criticality:', data['items'][0].get('criticality_score'))