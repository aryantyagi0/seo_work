import logging
from langchain_core.tools import tool

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

@tool
async def analyze_image_alt_text_tool(image_alt_texts: list[dict]) -> dict:
    """
    Analyzes images for the presence and content of alt text.
    
    Args:
        image_alt_texts: A list of dictionaries, where each dictionary represents an image with 'src' and 'alt' keys,
                         already extracted from the page.
        
    Returns:
        A dictionary with overall status, message, and details for each image.
    """
    if not image_alt_texts:
        return {"overall_status": "info", "message": "No images found with alt text data.", "details": []}

    missing_alt_count = 0
    images_analysis = []
    
    for img_data in image_alt_texts:
        src = img_data.get('src')
        alt = img_data.get('alt', '').strip()
        
        if not alt:
            missing_alt_count += 1
            status = "missing"
            message = "Alt text is missing or empty."
        else:
            status = "found"
            message = "Alt text is present."
            
        images_analysis.append({"src": src, "alt": alt, "status": status, "message": message})
        
    overall_status = "success" if missing_alt_count == 0 else "warning"
    overall_message = f"{missing_alt_count} images found with missing or empty alt text out of {len(images_analysis)}." if images_analysis else "No images found."
    
    return {"overall_status": overall_status, "message": overall_message, "details": images_analysis}

