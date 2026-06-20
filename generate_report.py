import os
import ast

def analyze_python_file(filepath):
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()
        tree = ast.parse(content)
        
        classes = []
        functions = []
        module_docstring = ast.get_docstring(tree)
        
        for node in tree.body:
            if isinstance(node, ast.ClassDef):
                methods = []
                for m in node.body:
                    if isinstance(m, ast.FunctionDef) or isinstance(m, ast.AsyncFunctionDef):
                        methods.append(m.name)
                class_doc = ast.get_docstring(node)
                classes.append({'name': node.name, 'methods': methods, 'doc': class_doc})
            elif isinstance(node, ast.FunctionDef) or isinstance(node, ast.AsyncFunctionDef):
                func_doc = ast.get_docstring(node)
                functions.append({'name': node.name, 'doc': func_doc})
                
        return {'docstring': module_docstring, 'classes': classes, 'functions': functions, 'lines': len(content.splitlines())}
    except Exception as e:
        return {'error': str(e)}

def generate_report():
    report = "# SG_CUBE Codebase Structural Report\n\n"
    report += "This report contains a structural breakdown of every file in the project.\n\n"
    
    total_files = 0
    total_lines = 0
    
    file_reports = []
    
    for root, dirs, files in os.walk('.'):
        if '.venv' in root or '.git' in root or '__pycache__' in root or 'node_modules' in root:
            continue
        for file in files:
            if file in ['generate_report.py', 'CODEBASE_REPORT.md']:
                continue
            filepath = os.path.normpath(os.path.join(root, file))
            total_files += 1
            
            file_report = f"## `{filepath}`\n"
            
            if file.endswith('.py'):
                analysis = analyze_python_file(filepath)
                if 'error' in analysis:
                    file_report += f"**Error parsing file:** {analysis['error']}\n\n"
                else:
                    lines = analysis.get('lines', 0)
                    total_lines += lines
                    file_report += f"- **Type:** Python Module\n- **Lines:** {lines}\n\n"
                    
                    if analysis['docstring']:
                        file_report += f"**Module Docstring:**\n```text\n{analysis['docstring']}\n```\n\n"
                        
                    if analysis['classes']:
                        file_report += "### Classes\n"
                        for cls in analysis['classes']:
                            file_report += f"- **`{cls['name']}`**\n"
                            if cls['doc']:
                                doc_preview = cls['doc'].split('\n')[0][:100]
                                file_report += f"  - *Doc:* {doc_preview}\n"
                            if cls['methods']:
                                file_report += f"  - *Methods:* {', '.join(cls['methods'])}\n"
                        file_report += "\n"
                        
                    if analysis['functions']:
                        file_report += "### Functions\n"
                        for func in analysis['functions']:
                            file_report += f"- **`{func['name']}`**\n"
                            if func['doc']:
                                doc_preview = func['doc'].split('\n')[0][:100]
                                file_report += f"  - *Doc:* {doc_preview}\n"
                        file_report += "\n"
            else:
                try:
                    with open(filepath, 'r', encoding='utf-8') as f:
                        lines = len(f.readlines())
                        total_lines += lines
                    file_report += f"- **Type:** Non-Python File\n- **Lines:** {lines}\n\n"
                except Exception:
                    file_report += f"- **Type:** Binary File\n\n"
                    
            file_reports.append(file_report)
            
    file_reports.sort()
    
    report += f"**Total Files Scanned:** {total_files}\n"
    report += f"**Total Lines of Code:** {total_lines}\n\n"
    
    report += "---\n\n"
    
    for fr in file_reports:
        report += fr + "---\n\n"
                
    with open('CODEBASE_REPORT.md', 'w', encoding='utf-8') as f:
        f.write(report)
    print(f"Report generated successfully. Analyzed {total_files} files with a total of {total_lines} lines.")

if __name__ == '__main__':
    generate_report()
