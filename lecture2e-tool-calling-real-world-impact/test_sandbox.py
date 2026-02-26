"""
Test script to verify sandbox tools are working correctly.
Run this after starting the sandbox container.
"""

from sandbox_tools import (
    check_sandbox_status,
    sandbox_list_files,
    sandbox_write_file,
    sandbox_read_file,
    sandbox_create_directory,
    sandbox_exec_python,
    sandbox_delete_file
)

def test_sandbox():
    print("Testing Sandbox Tools")
    print("=" * 60)
    
    # Test 1: Check status
    print("\n1. Checking sandbox status...")
    status = check_sandbox_status()
    print(f"   {status}")
    
    if "not running" in status.lower():
        print("\n   ⚠️  Please start the container first:")
        print("   docker run -d --name sandbox-bot --rm sandbox-bot:latest")
        return
    
    # Test 2: List initial files
    print("\n2. Listing initial files...")
    files = sandbox_list_files("/sandbox")
    print(f"   {files[:100]}...")
    
    # Test 3: Create directory
    print("\n3. Creating test directory...")
    result = sandbox_create_directory("/sandbox/test")
    print(f"   {result}")
    
    # Test 4: Write file
    print("\n4. Writing test file...")
    result = sandbox_write_file("/sandbox/test/hello.txt", "Hello from the sandbox!")
    print(f"   {result}")
    
    # Test 5: Read file
    print("\n5. Reading test file...")
    content = sandbox_read_file("/sandbox/test/hello.txt")
    print(f"   Content: {content}")
    
    # Test 6: Execute Python
    print("\n6. Executing Python code...")
    code = "print('Python works!'); print(2 + 2)"
    result = sandbox_exec_python(code)
    print(f"   {result}")
    
    # Test 7: List files again
    print("\n7. Listing files after changes...")
    files = sandbox_list_files("/sandbox/test")
    print(f"   {files}")
    
    # Test 8: Delete file
    print("\n8. Deleting test file...")
    result = sandbox_delete_file("/sandbox/test/hello.txt")
    print(f"   {result}")
    
    print("\n" + "=" * 60)
    print("✓ All tests completed!")
    print("\nYou can now run: python toolbot_sandbox.py")

if __name__ == "__main__":
    test_sandbox()
