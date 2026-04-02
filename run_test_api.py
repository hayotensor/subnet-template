import sys
from unittest.mock import MagicMock

# --- Mock aiohttp and web for testing environment without internet ---
mock_aiohttp = MagicMock()
mock_web = MagicMock()
mock_aiohttp.web = mock_web
sys.modules['aiohttp'] = mock_aiohttp
sys.modules['aiohttp.web'] = mock_web

import asyncio

# Set up mock client session
class MockResp:
    def __init__(self, method, url, data):
        self.method = method
        self.url = url
        self.data = data
        
    async def read(self):
        return f"Mock Unary Response to: {self.data.decode('utf-8') if self.data else ''}".encode('utf-8')

    class Content:
        async def iter_any(self):
            for i in range(5):
                yield f"Mock Chunk {i}\n".encode('utf-8')
                await asyncio.sleep(0.01)
            yield b"Done mock streaming!"
    
    @property
    def content(self):
        return self.Content()

    async def __aenter__(self):
        return self
        
    async def __aexit__(self, exc_type, exc, tb):
        pass

class MockSession:
    def request(self, method, url, headers, data):
        return MockResp(method, url, data)
        
    async def __aenter__(self):
        return self
        
    async def __aexit__(self, exc_type, exc, tb):
        pass

mock_aiohttp.ClientSession = MockSession
# -------------------------------------------------------------------

import logging
from libp2p import new_host
from multiaddr import Multiaddr

from subnet.protocols.api_protocol import ApiProtocol

class MockSubnetInfoTracker:
    pass

async def main():
    logging.basicConfig(level=logging.WARNING)
    
    # Create node 1 (The client)
    host1 = new_host()
    
    # Create node 2 (The Server/Router)
    host2 = new_host()
    
    # Node 2 API Routes
    api_routes = {
        "unary_test": "http://localhost:8080/unary",
        "stream_test": "http://localhost:8080/stream"
    }
    
    proto1 = ApiProtocol(host1, MockSubnetInfoTracker())
    proto2 = ApiProtocol(host2, MockSubnetInfoTracker(), api_routes=api_routes)
    
    await host1.get_network().listen(Multiaddr("/ip4/127.0.0.1/tcp/0"))
    await host2.get_network().listen(Multiaddr("/ip4/127.0.0.1/tcp/0"))
    
    # Get Node 2's listen address
    maddrs = host2.get_network().listeners()[0].get_addrs()
    target_maddr = maddrs[0].with_pid(host2.get_id())
    
    print(f"\nNode 2 listening on {target_maddr}")
    
    print("\n--- Testing Unary Request ---")
    response_bytes = await proto1.call_remote(
        destination=target_maddr,
        route="unary_test",
        method="POST",
        body=b"Hello API",
    )
    print(f"Unary response: {response_bytes.decode('utf-8', errors='replace')}")
    
    print("\n--- Testing Stream Request ---")
    async for chunk in proto1.stream_remote(
        destination=target_maddr,
        route="stream_test",
        method="GET",
    ):
        print(f"Stream chunk: {chunk.decode('utf-8', errors='replace').strip()}")
        
    print("\nCleaning up...")
    await host1.get_network().close()
    await host2.get_network().close()

if __name__ == "__main__":
    asyncio.run(main())
