import os
import csv
import argparse
import json
import xml.etree.ElementTree as ET
from github import Github
from dotenv import load_dotenv
from base64 import b64decode
import openai

#Tokens
load_dotenv()
g = Github(os.getenv("PYGITHUB_TOKEN"))
openai.api_key = os.getenv("OPENAI_API_KEY")

def check_dir(directory):
    if not os.path.exists(directory):
        os.makedirs(directory)

def check_depedencies(repo):
    known_files = [
        "pom.xml", "package.json", "requirements.txt", "setup.py",
        "build.gradle", "Cargo.toml", "composer.json", "Gemfile"
    ]
    try:
        contents = repo.get_contents("")
        for file in contents:
            if file.name in known_files:
                return file.name
        return None
    except:
        return None

def parse_pom(content):
    try:
        ns = {'m': 'http://maven.apache.org/POM/4.0.0'}
        root = ET.fromstring(content)
        return [
            f"{d.find('m:groupId', ns).text}:{d.find('m:artifactId', ns).text}:{d.find('m:version', ns).text if d.find('m:version', ns) is not None else 'latest'}"
            for d in root.findall('.//m:dependency', ns)
        ]
    except:
        return []

def parse_requirements_txt(content):
    return [line.strip() for line in content.splitlines() if line and not line.startswith("#")]

def parse_package_json(content):
    try:
        data = json.loads(content)
        deps = data.get("dependencies", {})
        return [f"{k}:{v}" for k, v in deps.items()]
    except:
        return []

def llm_extarctor(readme_text):
    prompt = f"""
Given the following README, extract a list of software dependencies (libraries, tools, packages) it requires. Ignore tools like git/make or OS. Provide a comma-separated list.

README:
{readme_text}
"""
    try:
        response = openai.ChatCompletion.create(
            model="gpt-3.5-turbo",
            messages=[{"role": "user", "content": prompt}],
            temperature=0
        )
        return response['choices'][0]['message']['content'].strip()
    except Exception as e:
        print("LLM fallback failed:", e)
        return ""

def extract_dependencies(repo):
    filename = check_depedencies(repo)
    if filename:
        try:
            content = b64decode(repo.get_contents(filename).content).decode("utf-8")
            if filename == "pom.xml":
                return parse_pom(content)
            elif filename == "package.json":
                return parse_package_json(content)
            elif filename == "requirements.txt":
                return parse_requirements_txt(content)
        except:
            return []

    # fallback to README
    try:
        readme = repo.get_readme()
        content = b64decode(readme.content).decode("utf-8")
        llm_result = extract_dependencies_with_llm(content)
        return [x.strip() for x in llm_result.split(",") if x.strip()]
    except:
        return []

def fetch_repository_data(user_name, output_csv_file, specific_repo=None):
    check_dir(os.path.dirname(output_csv_file))
    repositories = [g.get_repo(f"{user_name}/{specific_repo}")] if specific_repo else g.get_user(user_name).get_repos()

    fieldnames = [
        'softwareName', 'identifier', 'description', 'sourceCodeURL', 'creationDate', 'lastModified',
        'officialWebsite', 'hasLicense', 'isOpenSource', 'hasKeyword', 'hasPublisher', 'hasContributor',
        'hasIssue', 'programmingLanguage', 'hasBranch', 'hasDependency'
    ]

    with open(output_csv_file, 'w', newline='', encoding='utf-8') as csvfile:
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
        writer.writeheader()

        for repo in repositories:
            try:
                contributors = repo.get_contributors()
                contributor_names = ', '.join([c.login for c in contributors])

                languages = repo.get_languages()
                main_language = max(languages, key=languages.get) if languages else ''

                branches = repo.get_branches()
                branch_names = ', '.join([b.name for b in branches])

                topics = ', '.join(repo.get_topics()) if hasattr(repo, "get_topics") else ''

                dependencies = extract_dependencies(repo)

                repo_info = {
                    'softwareName': repo.name,
                    'identifier': repo.full_name,
                    'description': repo.description or '',
                    'sourceCodeURL': repo.html_url,
                    'creationDate': repo.created_at.date(),
                    'lastModified': repo.updated_at.date(),
                    'officialWebsite': repo.homepage or '',
                    'hasLicense': repo.license.name if repo.license else 'None',
                    'isOpenSource': str(not repo.private).lower(),
                    'hasKeyword': topics,
                    'hasPublisher': repo.owner.login,
                    'hasContributor': contributor_names,
                    'hasIssue': repo.open_issues_count,
                    'programmingLanguage': main_language,
                    'hasBranch': branch_names,
                    'hasDependency': ', '.join(dependencies)
                }

                writer.writerow(repo_info)
                print(f"✔️ Processed: {repo.full_name}")
            except Exception as e:
                print(f"❌ Failed to process {repo.full_name}: {e}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="GitHub → Softology metadata extractor with dependency parsing.")
    parser.add_argument("user_name", help="GitHub username or organization.")
    parser.add_argument("output_filename", help="Output CSV file name.")
    parser.add_argument("--repo", help="(Optional) Specific repository name.", required=False)
    args = parser.parse_args()

    output_directory = "pyGitHub-Crawler"
    output_csv_file = os.path.join(output_directory, args.output_filename)

    fetch_repository_data(args.user_name, output_csv_file, specific_repo=args.repo)
