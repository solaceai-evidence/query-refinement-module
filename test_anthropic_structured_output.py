"""Test script to understand Anthropic structured output behavior with litellm."""
import asyncio
import json
import os
from pydantic import BaseModel, Field

try:
    import litellm
    litellm.set_verbose = True  # Enable verbose logging
except ImportError:
    print("❌ litellm not installed")
    exit(1)


class TestResponse(BaseModel):
    """Simple test response model."""
    complete: bool = Field(description="Whether task is complete")
    message: str = Field(description="A message")


async def test_structured_output():
    """Test structured output with Anthropic/Claude."""
    
    # Get API key from environment
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        print("❌ ANTHROPIC_API_KEY not set")
        return
    
    # Test with Claude Haiku
    model = "claude-3-5-haiku-20241022"
    
    messages = [
        {"role": "system", "content": "You are a helpful assistant. Always respond in JSON format."},
        {"role": "user", "content": 'Respond with: complete=true, message="Hello World"'}
    ]
    
    print("=" * 70)
    print("TEST 1: Pydantic Model as response_format")
    print("=" * 70)
    
    try:
        response1 = await litellm.acompletion(
            model=model,
            messages=messages,
            response_format=TestResponse,  # Pydantic model
            api_key=api_key,
        )
        
        print(f"Response type: {type(response1)}")
        print(f"Response keys: {response1.keys() if isinstance(response1, dict) else 'N/A'}")
        
        if hasattr(response1, 'model_dump'):
            response1 = response1.model_dump()
        
        message_obj = response1["choices"][0]["message"]
        print(f"Message type: {type(message_obj)}")
        print(f"Has 'parsed' attr: {hasattr(message_obj, 'parsed')}")
        
        if hasattr(message_obj, 'parsed'):
            print(f"Parsed value: {message_obj.parsed}")
            print(f"Parsed type: {type(message_obj.parsed)}")
        
        content = message_obj.get("content") if isinstance(message_obj, dict) else getattr(message_obj, "content", None)
        print(f"Content: {content}")
        
    except Exception as e:
        print(f"❌ Test 1 failed: {e}")
        import traceback
        traceback.print_exc()
    
    print("\n" + "=" * 70)
    print("TEST 2: JSON object dict as response_format")
    print("=" * 70)
    
    try:
        response2 = await litellm.acompletion(
            model=model,
            messages=messages,
            response_format={"type": "json_object"},  # JSON schema dict
            api_key=api_key,
        )
        
        print(f"Response type: {type(response2)}")
        
        if hasattr(response2, 'model_dump'):
            response2 = response2.model_dump()
        
        message_obj = response2["choices"][0]["message"]
        content = message_obj.get("content") if isinstance(message_obj, dict) else getattr(message_obj, "content", None)
        print(f"Content: {content}")
        
        # Try to parse JSON
        try:
            parsed = json.loads(content)
            print(f"✓ Successfully parsed JSON: {parsed}")
        except:
            print(f"❌ Failed to parse as JSON")
        
    except Exception as e:
        print(f"❌ Test 2 failed: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(test_structured_output())
