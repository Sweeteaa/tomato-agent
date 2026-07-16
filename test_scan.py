import asyncio
from agent.workflows.project_scan_workflow import run_project_scan

class MockRegistry:
    def execute_tool(self, tool_name, args):
        print(f'  Tool: {tool_name} args={args}')
        from agent.tools.filesystem import list_dir, read_file, scan_menu_structure
        if tool_name == 'list_dir':
            return list_dir(args['path'], args.get('recursive', False), args.get('max_depth', 5))
        elif tool_name == 'read_file':
            return read_file(args['path'], args.get('start_line', 0), args.get('end_line', 0))
        elif tool_name == 'scan_menu_structure':
            return scan_menu_structure(args['project_path'])
        return ''

async def test():
    async for evt in run_project_scan('D:/projects/天津三院HCC专病库', MockRegistry()):
        t = evt.get('type')
        m = evt.get('message', evt.get('tool', ''))
        print(f'{t}: {m}')

if __name__ == '__main__':
    asyncio.run(test())
