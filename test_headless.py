import asyncio
from backend.daemon.ui import SGCubeApp

async def run_test():
    app = SGCubeApp()
    async with app.run_test() as pilot:
        # wait 1 second for mount and initial timers to tick
        await pilot.pause(1.0)
        print("TEST PASSED: No exceptions during mount and animations!")

if __name__ == "__main__":
    asyncio.run(run_test())
