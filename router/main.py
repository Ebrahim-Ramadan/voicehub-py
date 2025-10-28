from fastapi import FastAPI, Request, HTTPException, WebSocket
from fastapi.responses import JSONResponse, HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from typing import Any, Dict, List, Set
import asyncio
import uvicorn
import json
import os
import pickle

# Load menu data
with open("menu.json", "r", encoding="utf-8") as f:
    menu_items = json.load(f)

app = FastAPI(title="Webhook Receiver")

# Serve static files (if you have CSS/images)
app.mount("/static", StaticFiles(directory="static"), name="static")

# Update the models to match the incoming JSON structure
class OrderItem(BaseModel):
    item_id: Any  # Accept both string and int
    size: str
    quantity: int

class Order(BaseModel):
    items: List[OrderItem]

class FinalOrder(BaseModel):
    order: Order | None = None
    items: List[OrderItem] | None = None

    def get_items(self) -> List[OrderItem]:
        """Get items regardless of structure"""
        if self.order:
            return self.order.items
        return self.items if self.items else []

class WebhookPayload(BaseModel):
    Final_order: str
    event_type: str = Field(default="unknown")
    data: Dict[str, Any] = Field(default_factory=dict)
    
    class Config:
        extra = "allow"

class RecommendationPayload(BaseModel):
    items_ids: str

def find_menu_item(item_id: str) -> dict:
    """Find menu item by matching either item ID, name_en, or name_ar (case insensitive)"""
    item_id = item_id.lower().strip()
    print(f"🔍 Searching for item: {item_id}")
    
    for item in menu_items:
        name_en = str(item.get('name_en', '')).lower()
        name_ar = str(item.get('name_ar', '')).lower()
        item_num = str(item.get('item', '')).lower()
        
        print(f"Checking: {name_en} / {name_ar} / #{item_num}")
        
        if (item_num == item_id or 
            name_en == item_id or 
            'americano' in name_en or  # Special case for 'americano'
            name_ar == item_id):
            print(f"✅ Found match: {item}")
            return item
            
    print(f"❌ No match found for: {item_id}")
    return None

def get_size_key(size: str) -> str:
    """Convert Arabic/English size names to standard keys"""
    size_mapping = {
        "وسط": "medium",
        "موسط": "medium",
        "صغير": "small", 
        "كبير": "large",
        "medium": "medium",
        "small": "small",
        "large": "large"
    }
    return size_mapping.get(size.lower(), size.lower())

# Store recommendations separately
last_recommendations = []  # Store recommended items
last_order_details = []  # Store the last order

STATE_FILE = "state.pkl"

def save_state():
    with open(STATE_FILE, "wb") as f:
        pickle.dump({
            "last_order_details": last_order_details,
            "last_recommendations": last_recommendations
        }, f)

def load_state():
    global last_order_details, last_recommendations
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, "rb") as f:
            data = pickle.load(f)
            last_order_details = data.get("last_order_details", [])
            last_recommendations = data.get("last_recommendations", [])

def generate_html_content(order_details: List[dict] = None, recommendations: List[dict] = None) -> str:
    show_recommendations = not order_details and recommendations  # Show recommendations only if no order items
    html = ""
    
    if show_recommendations:
        html += """
        <div class="recommendations-grid">
        """
        for idx, item in enumerate(recommendations):
            menu_item = item['menu_item']
            size = 'medium'  # Default size for recommendations
            price = menu_item['sizes'].get(size, 0)
            
            image_path = f'static/{menu_item.get("image", "")}'
            has_image = os.path.exists(image_path) if menu_item.get("image") else False
            image_html = f"""
                <img class="item-image" 
                    src="/static/{menu_item['image']}" 
                    alt="{menu_item['name_en']}"
                    data-size="{size}"
                    loading="lazy">
            """ if has_image else f'<div class="placeholder">Item #{menu_item.get("item", "N/A")}</div>'

            html += f"""
                <div class="item-card" style="animation-delay: {idx * 0.1}s">
                    <div class="image-container">
                        {image_html}
                        <div class="size-badge">{size}</div>
                    </div>
                    <div class="item-details">
                        <div class="item-name">{menu_item['name_en']}</div>
                        <div class="item-price">{price:.2f} {menu_item['currency']}</div>
                    </div>
                </div>
            """
        html += """
        </div>
        """
    else:
        html += """
        <div class="grid-container">
        """
        # Calculate items and total
        total = 0
        breakdown_items = []
        
        for idx, item in enumerate(order_details):
            menu_item = item['menu_item']
            size = get_size_key(item['size'])
            quantity = item['quantity']
            price = menu_item['sizes'].get(size, 0)
            subtotal = price * quantity
            total += subtotal
            
            breakdown_items.append({
                'name': menu_item['name_en'],
                'quantity': quantity,
                'price': price,
                'subtotal': subtotal
            })
            
            image_path = f'static/{menu_item.get("image", "")}'
            has_image = os.path.exists(image_path) if menu_item.get("image") else False
            image_html = f"""
                <img class="item-image" 
                    src="/static/{menu_item['image']}" 
                    alt="{menu_item['name_en']}"
                    data-size="{size}"
                    loading="lazy">
            """ if has_image else f'<div class="placeholder">Item #{menu_item.get("item", "N/A")}</div>'

            html += f"""
                <div class="item-card" style="animation-delay: {idx * 0.1}s">
                    <div class="image-container">
                        {image_html}
                        <div class="quantity-badge">{quantity}</div>
                        <div class="size-badge">{size}</div>
                    </div>
                    <div class="item-details">
                        <div class="item-name">{menu_item['name_en']}</div>
                        <div class="item-price">{price:.2f} {menu_item['currency']}</div>
                    </div>
                </div>
            """

        html += """
            </div>
            <div class="total-container">
                <div class="order-breakdown">
        """
        
        for item in breakdown_items:
            html += f"""
                <div class="breakdown-item">
                    <span>{item['name']} × {item['quantity']}</span>
                    <span>{item['subtotal']:.2f} KWD</span>
                </div>
            """
        
        html += f"""
                </div>
                <div class="total-row">
                    <span class="total-label">Total</span>
                    <span class="total-amount">KWD {total:.2f}</span>
                </div>
            </div>
        """
    return html

@app.post("/recommendations")
async def recommendations_endpoint(request: Request):
    global last_recommendations
    try:
        body = await request.json()
        print("\n=== Recommendations Request ===")
        print(f"📨 Raw body: {json.dumps(body, indent=2, ensure_ascii=False)}")
        
        # Validate payload
        payload = RecommendationPayload(**body)
        item_ids = payload.items_ids.split(",")
        item_ids = [id.strip() for id in item_ids if id.strip()]
        
        if not item_ids:
            print("\n❌ No valid item IDs in recommendations")
            return JSONResponse(
                status_code=400,
                content={"error": "No valid item IDs provided"}
            )
        
        # Process recommended items
        recommendations = []
        not_found_items = []
        
        print("\n🔎 Looking up recommended items:")
        for item_id in item_ids:
            print(f"\nSearching for item_id: {item_id}")
            menu_item = find_menu_item(item_id)
            
            if not menu_item:
                not_found_items.append(item_id)
                print(f"❌ Item not found: {item_id}")
                continue
            
            print(f"✅ Found item: {menu_item.get('name_en')} ({menu_item.get('name_ar')})")
            recommendations.append({
                "menu_item": menu_item
            })
        
        if not_found_items:
            print(f"\n❌ Some items not found: {not_found_items}")
            return JSONResponse(
                status_code=404,
                content={"error": f"Items not found: {', '.join(not_found_items)}"}
            )
        
        if not recommendations:
            print("\n❌ No valid items in recommendations")
            return JSONResponse(
                status_code=400,
                content={"error": "No valid items in recommendations"}
            )
        
        # Store recommendations and persist
        last_recommendations = recommendations
        save_state()
        print(f"\n✅ Recommendations stored with {len(recommendations)} items")
        
        # Notify all connected WebSocket clients with recommendations data
        await notify_clients({
            "type": "recommendations",
            "data": recommendations
        })
        
        return JSONResponse(content={"status": "success"})

    except Exception as e:
        print(f"\n💥 Unexpected error: {str(e)}")
        return JSONResponse(
            status_code=500,
            content={"error": f"Server error: {str(e)}"}
        )

@app.post("/webhook")
async def webhook_endpoint(request: Request):
    global last_order_details
    try:
        body = await request.json()
        print("\n=== Webhook Request ===")
        print(f"📨 Raw body: {json.dumps(body, indent=2, ensure_ascii=False)}")
        
        try:
            final_order_data = json.loads(body.get("Final_order", "").strip())
            print(f"\n🔍 Parsed Final_order: {json.dumps(final_order_data, indent=2, ensure_ascii=False)}")
            
            # Validate with flexible model
            final_order = FinalOrder(**final_order_data)
            order_items = final_order.get_items()
            
            if not order_items:
                raise ValueError("No items found in order")
                
            print(f"\n✅ Validated order structure")
            print(f"\n📋 Order items: {len(order_items)} items")
            for idx, item in enumerate(order_items, 1):
                print(f"  Item {idx}: id={item.item_id}, size={item.size}, qty={item.quantity}")
            
        except json.JSONDecodeError as e:
            print(f"\n❌ JSON parsing error: {str(e)}")
            return JSONResponse(
                status_code=400,
                content={"error": f"Invalid JSON format: {str(e)}"}
            )
        except Exception as e:
            print(f"\n❌ Validation error: {str(e)}")
            return JSONResponse(
                status_code=400,
                content={"error": f"Invalid order format: {str(e)}"}
            )

        # Process items
        order_details = []
        not_found_items = []
        
        print("\n🔎 Looking up menu items:")
        for item in order_items:
            item_id = str(item.item_id)
            print(f"\nSearching for item_id: {item_id}")
            menu_item = find_menu_item(item_id)
            
            if not menu_item:
                not_found_items.append(item_id)
                print(f"❌ Item not found: {item_id}")
                continue
            
            print(f"✅ Found item: {menu_item.get('name_en')} ({menu_item.get('name_ar')})")
            order_details.append({
                "menu_item": menu_item,
                "size": item.size,
                "quantity": item.quantity
            })
        
        if not_found_items:
            print(f"\n❌ Some items not found: {not_found_items}")
            return JSONResponse(
                status_code=404,
                content={"error": f"Items not found: {', '.join(not_found_items)}"}
            )
        
        if not order_details:
            print("\n❌ No valid items in order")
            return JSONResponse(
                status_code=400,
                content={"error": "No valid items in order"}
            )
        
        # Store and persist order
        last_order_details = order_details
        save_state()
        print(f"\n✅ Order stored with {len(order_details)} items")
        
        # Notify all connected WebSocket clients with order data
        await notify_clients({
            "type": "order",
            "data": order_details
        })
        
        return JSONResponse(content={"status": "success"})

    except Exception as e:
        print(f"\n💥 Unexpected error: {str(e)}")
        return JSONResponse(
            status_code=500,
            content={"error": f"Server error: {str(e)}"}
        )

@app.get("/")
async def view_order():
    # DO NOT reset last_order_details or last_recommendations here!
    return HTMLResponse(
        content="""
        <html>
        <head>
            <title>No Order</title>
            <style>
                .scrollbar-hidden::-webkit-scrollbar {
                    display: none;
                }
                .scrollbar-hidden {
                    -ms-overflow-style: none;
                    scrollbar-width: none;
                }
                ::-webkit-scrollbar {
                    height: 0;
                    width: 0;
                }
                ::-webkit-scrollbar-track {
                    height: 0;
                    border-radius: 0;
                }
                ::-webkit-scrollbar-thumb {
                    height: 0;
                    border-radius: 0;
                }
                body { 
                    background: #FDFDFD; 
                    display: flex; 
                    align-items: center; 
                    justify-content: center; 
                    height: 100vh; 
                    margin: 0; 
                    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
                }
                video { 
                    max-width: 50vw; 
                    max-height: 35vh;
                }
                @keyframes slideUpFade {
  0% { opacity: 0; transform: translateY(24px); }
  60% { opacity: 0.8; transform: translateY(6px); }
  100% { opacity: 1; transform: translateY(0); }
}
                .hello-text {
                    font-size: 20px;
                    font-weight: 700;
                    opacity: 0;
                    visibility: visible;
                }
                .hello-text.animate {
                    animation: slideUpFade 800ms cubic-bezier(.2,.9,.3,1) forwards;
                }
                .logo-container {
                    position: absolute;
                    top: 16px;
                    left: 16px;
                    z-index: 2;
                }
                .logo {
                    border-radius: 50%;
                    width: 40px;
                    height: auto;
                }
               @keyframes bounce-slow {
  0%, 100% { -webkit-transform: scale(1) translateY(0); transform: scale(1) translateY(0); }
  35% { -webkit-transform: scale(1.1) translateY(-5px); transform: scale(1.1) translateY(-5px); }
  45% { -webkit-transform: scale(0.95) translateY(2px); transform: scale(0.95) translateY(2px); }
  75% { -webkit-transform: scale(1.05) translateY(-2px); transform: scale(1.05) translateY(-2px); }
}
                .animate-bounce-slow {
                    animation: bounce-slow 6s ease-in-out infinite;
                }
                .DqVoiceWidget__chat,
                .DqVoiceWidget__chat[style],
                .DqVoiceWidget__chat[style*="display"],
                .DqVoiceWidget__chat[style*="block"] {
                    display: none !important;
                    visibility: hidden !important;
                    opacity: 0 !important;
                    pointer-events: none !important;
                }
               @keyframes bounceIn {
  0% { opacity: 0; -webkit-transform: scale(0.3) rotate(-12deg); transform: scale(0.3) rotate(-12deg); }
  50% { opacity: 0.8; -webkit-transform: scale(1.05) rotate(2deg); transform: scale(1.05) rotate(2deg); }
  70% { -webkit-transform: scale(0.98) rotate(-1deg); transform: scale(0.98) rotate(-1deg); }
  100% { opacity: 1; -webkit-transform: scale(1) rotate(0deg); transform: scale(1) rotate(0deg); }
}
                @keyframes float {
  0% { -webkit-transform: translateY(0) translateX(0); transform: translateY(0) translateX(0); }
  25% { -webkit-transform: translateY(-20px) translateX(10px); transform: translateY(-20px) translateX(10px); }
  50% { -webkit-transform: translateY(0) translateX(20px); transform: translateY(0) translateX(20px); }
  75% { -webkit-transform: translateY(20px) translateX(10px); transform: translateY(20px) translateX(10px); }
  100% { -webkit-transform: translateY(0) translateX(0); transform: translateY(0) translateX(0); }
}
                .background-balls {
                    position: fixed;
                    top: 0;
                    left: 0;
                    width: 100%;
                    height: 100%;
                    pointer-events: none;
                    z-index: -1;
                }
                .ball {
                    position: absolute;
                    background: radial-gradient(circle at 30%, rgba(0, 102, 255, 0.3), transparent 70%);
                    border-radius: 50%;
                    filter: blur(10px);
                    will-change: transform;
  animation: float 10s ease-in-out infinite;
                    opacity: 0.3;
                }
                /* Respect reduced motion preferences */
@media (prefers-reduced-motion: reduce) {
  .item-card, .ball, .hello-text, .animate-bounce-slow {
    animation: none !important;
    transform: none !important;
    opacity: 1 !important;
  }
}
                .ball:nth-child(1) {
                    width: 80px;
                    height: 80px;
                    top: 10%;
                    left: 15%;
                    animation-duration: 12s;
                }
                .ball:nth-child(2) {
                    width: 120px;
                    height: 120px;
                    top: 30%;
                    right: 20%;
                    animation-duration: 15s;
                    animation-delay: 2s;
                }
                .ball:nth-child(3) {
                    width: 60px;
                    height: 60px;
                    bottom: 25%;
                    left: 30%;
                    animation-duration: 13s;
                    animation-delay: 1s;
                }
                .grid-container {
                    display: flex;
                    flex-wrap: wrap;
                    justify-content: center;
                    gap: 24px;
                    margin-bottom: 120px;
                    padding: 12px;
                    position: relative;
                    z-index: 1;
                }
                .recommendations-grid {
                    display: flex;
                    flex-wrap: wrap;
                    justify-content: center;
                    gap: 24px;
                    padding: 12px;
                    position: relative;
                    z-index: 1;
                    height: 100vh;
                    overflow-y: auto;
                }
                .item-card {
                    background: white;
                    border-radius: 16px;
                    overflow: hidden;
                    box-shadow: 0 4px 6px rgba(0, 0, 0, 0.05);
                    transform: scale(0.3);
                    opacity: 0;
                    animation: bounceIn 0.6s cubic-bezier(0.68, -0.55, 0.265, 1.55) forwards;
                    width: 214px;
                }
                .item-card:hover {
                    transform: scale(1.02);
                    box-shadow: 0 8px 12px rgba(0, 0, 0, 0.15);
                    transition: all 0.3s ease;
                }
                .image-container {
                    position: relative;
                    width: 100%;
                    padding-bottom: 100%;
                    background: #f5f5f5;
                    overflow: hidden;
                }
                .item-image {
                    position: absolute;
                    top: 0;
                    left: 0;
                    width: 100%;
                    height: 100%;
                    object-fit: cover;
                    transform-origin: center;
                }
                .item-image[data-size="small"] {
                    transform: scale(1.2);
                }
                .item-image[data-size="medium"] {
                    transform: scale(1.6);
                }
                .item-image[data-size="large"] {
                    transform: scale(1.9);
                }
                .quantity-badge {
                    position: absolute;
                    top: 4px;
                    right: 4px;
                    background: #0066FF;
                    color: white;
                    width: 36px;
                    height: 36px;
                    border-radius: 50%;
                    display: flex;
                    align-items: center;
                    justify-content: center;
                    font-weight: 600;
                    font-size: 20px;
                    box-shadow: 0 2px 4px rgba(0, 102, 255, 0.3);
                }
                .size-badge {
                    position: absolute;
                    bottom: 8px;
                    right: 8px;
                    background: rgba(0, 0, 0, 0.25);
                    backdrop-filter: blur(4px);
                    color: white;
                    padding: 4px 8px;
                    border-radius: 12px;
                    font-size: 11px;
                    font-weight: 500;
                    text-transform: capitalize;
                }
                .item-details {
                    padding: 12px;
                }
                .item-name {
                    font-size: 14px;
                    font-weight: 600;
                    color: #1a1a1a;
                    margin-bottom: 4px;
                }
                .item-price {
                    display: flex;
                    justify-content: end;
                    color: #1a1a1a;
                    font-size: 15px;
                    font-weight: 500;
                }
                .total-container {
                    position: fixed;
                    bottom: 0;
                    left: 50%;
                    transform: translateX(-50%);
                    width: 50%;
                    background: white;
                    border-top: 1px solid #eee;
                    padding: 4px 16px 16px 16px;
                    box-shadow: 0 -4px 12px rgba(0, 0, 0, 0.1);
                }
               
                .order-breakdown {
                    font-size: 12px;
                    color: #666;
                }
                .breakdown-item {
                    display: flex;
                    justify-content: space-between;
                    margin-bottom: 4px;
                }
                .total-row {
                    display: flex;
                    justify-content: space-between;
                    align-items: center;
                    padding-top: 12px;
                    border-top: 1px solid #eee;
                }
                .total-label {
                    font-size: 15px;
                    font-weight: 500;
                }
                .total-amount {
                    color: #0066FF;
                    font-size: 14px;
                    font-weight: 700;
                }
            </style>
            <script src='https://voicehub.dataqueue.ai/DqVoiceWidget.js'></script>
            <script>
                console.log('Starting homepage script');
                let ws = new WebSocket(`ws://${window.location.host}/ws`);
                ws.onmessage = function(event) {
                    console.log('WebSocket message received:', event.data);
                    try {
                        const message = JSON.parse(event.data);
                        if (message.type === 'order' || message.type === 'recommendations') {
                            console.log('Processing', message.type);
                            updateContent(message.type, message.data);
                        }
                    } catch (e) {
                        console.error('Error parsing WebSocket message:', e);
                    }
                };
                ws.onerror = function(error) {
                    console.error('WebSocket error:', error);
                };
                ws.onclose = function() {
                    console.log('WebSocket connection closed');
                };

                document.addEventListener('DOMContentLoaded', () => {
                    console.log('DOM fully loaded');
                    setTimeout(() => {
                        console.log('Attempting to animate hello-text');
                        const el = document.querySelector('.hello-text');
                        if (el) {
                            console.log('Found hello-text element, adding animate class');
                            el.classList.add('animate');
                        } else {
                            console.error('hello-text element not found');
                        }
                    }, 2000);
                    // Fallback to show text if animation doesn't trigger
                    setTimeout(() => {
                        const el = document.querySelector('.hello-text');
                        if (el && !el.classList.contains('animate')) {
                            console.log('Animation fallback triggered');
                            el.style.opacity = '1';
                            el.style.transform = 'translateY(0)';
                        }
                    }, 3000);

                    // Fetch current state on page load
                    fetch('/current')
                        .then(res => res.json())
                        .then(msg => {
                            if (msg.type === 'order' || msg.type === 'recommendations') {
                                updateContent(msg.type, msg.data);
                            }
                        });
                });

                function updateContent(type, data) {
                    // Always hide initial content and remove it from DOM for robustness
                    const initialContent = document.getElementById('initial-content');
                    if (initialContent) {
                        initialContent.style.display = 'none';
                        // Optionally, remove from DOM to prevent any GIF from running
                        initialContent.parentNode && initialContent.parentNode.removeChild(initialContent);
                    }
                    const container = document.getElementById('dynamic-content');
                    if (!container) {
                        console.error('Dynamic content container not found');
                        return;
                    }
                    let html = '';
                    if (type === 'recommendations') {
                        html += '<div class="recommendations-grid">';
                        data.forEach((item, idx) => {
                            const menuItem = item.menu_item;
                            const size = 'medium';
                            const price = menuItem.sizes ? menuItem.sizes[size] || 0 : 0;
                            const imageHtml = menuItem.image ? 
                                `<img class="item-image" src="/static/${menuItem.image}" alt="${menuItem.name_en}" data-size="${size}" loading="lazy">` : 
                                `<div class="placeholder">Item #${menuItem.item || 'N/A'}</div>`;
                            html += `
                                <div class="item-card" style="animation-delay: ${idx * 0.1}s">
                                    <div class="image-container">
                                        ${imageHtml}
                                        <div class="size-badge">${size}</div>
                                    </div>
                                    <div class="item-details">
                                        <div class="item-name">${menuItem.name_en}</div>
                                        <div class="item-price">${price.toFixed(2)} ${menuItem.currency}</div>
                                    </div>
                                </div>
                            `;
                        });
                        html += '</div>';
                    } else if (type === 'order') {
                        html += '<div class="grid-container">';
                        let total = 0;
                        const breakdownItems = [];
                        data.forEach((item, idx) => {
                            const menuItem = item.menu_item;
                            const size = getSizeKey(item.size);
                            const quantity = item.quantity;
                            const price = menuItem.sizes ? menuItem.sizes[size] || 0 : 0;
                            const subtotal = price * quantity;
                            total += subtotal;
                            breakdownItems.push({
                                name: menuItem.name_en,
                                quantity: quantity,
                                subtotal: subtotal
                            });
                            const imageHtml = menuItem.image ? 
                                `<img class="item-image" src="/static/${menuItem.image}" alt="${menuItem.name_en}" data-size="${size}" loading="lazy">` : 
                                `<div class="placeholder">Item #${menuItem.item || 'N/A'}</div>`;
                            html += `
                                <div class="item-card" style="animation-delay: ${idx * 0.1}s">
                                    <div class="image-container">
                                        ${imageHtml}
                                        <div class="quantity-badge">${quantity}</div>
                                        <div class="size-badge">${size}</div>
                                    </div>
                                    <div class="item-details">
                                        <div class="item-name">${menuItem.name_en}</div>
                                        <div class="item-price">${price.toFixed(2)} ${menuItem.currency}</div>
                                    </div>
                                </div>
                            `;
                        });
                        html += '</div>';
                        html += '<div class="total-container"><div class="order-breakdown">';
                        breakdownItems.forEach(item => {
                            html += `
                                <div class="breakdown-item">
                                    <span>${item.name} × ${item.quantity}</span>
                                    <span>${item.subtotal.toFixed(2)} KWD</span>
                                </div>
                            `;
                        });
                        html += `</div><div class="total-row">
                            <span class="total-label">Total</span>
                            <span class="total-amount">KWD ${total.toFixed(2)}</span>
                        </div></div>`;
                    }
                    container.innerHTML = html;
                    // Re-apply animation delays
                    const cards = container.querySelectorAll('.item-card');
                    cards.forEach((card, index) => {
                        card.style.animationDelay = `${index * 0.1}s`;
                    });
                }

                function getSizeKey(size) {
                    const sizeMapping = {
                        "وسط": "medium",
                        "موسط": "medium",
                        "صغير": "small", 
                        "كبير": "large",
                        "medium": "medium",
                        "small": "small",
                        "large": "large"
                    };
                    return sizeMapping[size.toLowerCase()] || size.toLowerCase();
                }
            </script>
        </head>
        <body>
            <div class="background-balls">
                <div class="ball"></div>
                <div class="ball"></div>
                <div class="ball"></div>
            </div>
            <div id="initial-content" style="display:flex; flex-direction:column; align-items:center; justify-content:center; gap:16px;">
                <div class="logo-container">
                    <img class="logo" src="/static/anm/coffee-caribou-logo.png" alt="Logo">
                </div>
                                <div style="position: absolute; inset: 0; border-radius: 374px; opacity: 0.3; z-index: -1; background: radial-gradient(48.2% 50%, rgb(52, 150, 239) 0%, rgba(15, 28, 50, 0) 100%);"></div>

                <img src="/static/anm/coffee-love-animation.gif" class="animate-bounce-slow" alt="Coffee love animation">
                <div class="hello-text">Hello!</div>
                <div class="voice-widget-container">
                    <dq-voice agent-id='68f046cd815af002cbebfc7c' api-key='dqKey_891f22908457d4ec3fa25de1cad472fa59a940ffa8d5ec52fdd0196604980670ure6wzs3zu'></dq-voice>
                </div>
            </div>
            <div id="dynamic-content"></div>
        </body>
        </html>
        """
    )

# Add this endpoint to allow frontend to fetch current state on load
@app.get("/current")
async def get_current():
    if last_order_details:
        return {"type": "order", "data": last_order_details}
    elif last_recommendations:
        return {"type": "recommendations", "data": last_recommendations}
    else:
        return {"type": "none", "data": []}

@app.get("/debug-menu")
async def debug_menu():
    """Endpoint to view all menu items"""
    menu_debug = []
    for item in menu_items:
        menu_debug.append({
            'item': item.get('item'),
            'name_en': item.get('name_en'),
            'name_ar': item.get('name_ar')
        })
    return JSONResponse(content=menu_debug)

class WebSocketManager:
    def __init__(self):
        self.websockets: Set[WebSocket] = set()

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.websockets.add(websocket)

    def disconnect(self, websocket: WebSocket):
        self.websockets.discard(websocket)

    async def broadcast(self, message: dict):
        disconnected = []
        for ws in self.websockets:
            try:
                await ws.send_text(json.dumps(message))
            except Exception:
                disconnected.append(ws)
        for ws in disconnected:
            self.disconnect(ws)

ws_manager = WebSocketManager()

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await ws_manager.connect(websocket)
    try:
        while True:
            await websocket.receive_text()
    except Exception:
        ws_manager.disconnect(websocket)

async def notify_clients(message: dict):
    await ws_manager.broadcast(message)

if __name__ == "__main__":
    # Load saved state on startup
    load_state()
    # REMOVE reload=True and set workers=1 for prod/ngrok
    uvicorn.run("router.main:app", host="0.0.0.0", port=8000, workers=1)