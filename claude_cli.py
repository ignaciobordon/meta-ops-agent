#!/usr/bin/env python3
"""
Claude CLI Wrapper - Simple terminal interface for Claude AI
Usage: python claude_cli.py "your question here"
"""
import os
import sys
from anthropic import Anthropic

def main():
    # Get API key from environment
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        print("Error: ANTHROPIC_API_KEY not found in environment variables.")
        print("Set it with: $env:ANTHROPIC_API_KEY='your-key-here'")
        sys.exit(1)
    
    # Get user message from command line
    if len(sys.argv) < 2:
        print("Usage: python claude_cli.py \"your question here\"")
        sys.exit(1)
    
    user_message = " ".join(sys.argv[1:])
    
    # Initialize client
    client = Anthropic(api_key=api_key)
    
    print(f"\n🤖 Claude: ", end="", flush=True)
    
    # Stream the response
    with client.messages.stream(
        model="claude-sonnet-4-20250514",
        max_tokens=4096,
        messages=[{"role": "user", "content": user_message}]
    ) as stream:
        for text in stream.text_stream:
            print(text, end="", flush=True)
    
    print("\n")

if __name__ == "__main__":
    main()
