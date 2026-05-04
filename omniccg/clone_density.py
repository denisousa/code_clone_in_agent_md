import os
import pandas as pd
import xml.etree.ElementTree as ET

genealogy_results_path = os.path.abspath("genealogy_results")

# Count lines of code
def count_system_lines_of_code(directory, extension):
    total_lines = 0
    for root, _, files in os.walk(directory):
        for file_name in files:
            if file_name.endswith(extension):
                file_path = os.path.join(root, file_name)
                try:
                    with open(file_path, 'r', encoding='utf-8', errors='ignore') as file:
                        lines = file.readlines()
                        total_lines += len(lines)
                except Exception as e:
                    print(f"Error reading {file_path}: {e}")
    return total_lines

# Calculate cloned lines of code
def count_cloned_lines_of_code(xml_path):
    tree = ET.parse(xml_path)
    root = tree.getroot()
    total_lines = 0
    for cls in root.findall('class'):
        for source in cls.findall('source'):
            startline = int(source.get('startline'))
            endline = int(source.get('endline'))
            total_lines += (endline - startline)
    return total_lines

def compute_clone_density(ctx, language, repo_name, git_url, commit_index, commit_sha, author):
    system_lines = count_system_lines_of_code(os.path.abspath(ctx.paths.prod_data_dir), language)
    clones_lines = count_cloned_lines_of_code(ctx.paths.clone_detector_xml)
    clone_density_by_repo = round((clones_lines * 100) / system_lines, 2)
    
    return {
            "project": repo_name,
            "full_url": git_url,
            "commit_index": commit_index,
            "commit_sha": commit_sha,
            "author": author,
            "language": language,
            "system_loc": system_lines,
            "cloned_loc": clones_lines,
            "clone_density": clone_density_by_repo,
        }

def WriteCloneDensity(clone_density_rows, language, repo_complete_name):
    density_df = pd.DataFrame(clone_density_rows)
    clone_density_path = os.path.join(genealogy_results_path, f"{language}_{repo_complete_name}_clone_density.csv")
    density_df.to_csv(clone_density_path, index=False)
    print(f"\nSaved clone density data to {clone_density_path}")