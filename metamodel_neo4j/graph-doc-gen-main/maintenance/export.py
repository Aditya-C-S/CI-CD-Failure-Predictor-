import os
from database.neo4j_client import Neo4jClient
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser

def _export_static(nodes_raw, edges_raw, file_path, fmt):
    with open(file_path, "w") as f:
        if fmt == "mermaid":
            f.write("classDiagram\n")
            for n in nodes_raw:
                friendly_id = str(n["id"]).replace(":", "_").replace("-", "_").replace(".", "_").replace("/", "_")
                name = n.get("name", friendly_id)
                label = n["labels"][0] if n["labels"] else "Node"
                f.write(f"  class {friendly_id} {{\n    <<{label}>>\n    {name}\n  }}\n")

            for e in edges_raw:
                src = str(e["source"]).replace(":", "_").replace("-", "_").replace(".", "_").replace("/", "_")
                tgt = str(e["target"]).replace(":", "_").replace("-", "_").replace(".", "_").replace("/", "_")
                e_type = e["type"]
                rel = "*--" if e_type == "CONTAINS" else "-->"
                f.write(f"  {src} {rel} {tgt} : {e_type}\n")

        elif fmt == "plantuml":
            f.write("@startuml\n")
            for n in nodes_raw:
                friendly_id = str(n["id"]).replace(":", "_").replace("-", "_").replace(".", "_").replace("/", "_")
                name = n.get("name", friendly_id)
                label = n["labels"][0] if n["labels"] else "Node"
                f.write(f"class {friendly_id} <<{label}>> {{\n  {name}\n}}\n")

            for e in edges_raw:
                src = str(e["source"]).replace(":", "_").replace("-", "_").replace(".", "_").replace("/", "_")
                tgt = str(e["target"]).replace(":", "_").replace("-", "_").replace(".", "_").replace("/", "_")
                e_type = e["type"]
                rel = "*--" if e_type == "CONTAINS" else "-->"
                f.write(f"{src} {rel} {tgt} : {e_type}\n")
            f.write("@enduml\n")

        elif fmt == "drawio":
            f.write('<mxfile><diagram id="graph-augmented-documentation" name="Architecture"><mxGraphModel><root>\n')
            f.write('<mxCell id="0"/><mxCell id="1" parent="0"/>\n')
            
            y_pos = 0
            for i, n in enumerate(nodes_raw):
                friendly_id = str(n["id"])
                name = n.get("name", friendly_id)
                f.write(f'<mxCell id="{friendly_id}" value="{name}" style="rounded=1;whiteSpace=wrap;html=1;" vertex="1" parent="1">\n')
                f.write(f'  <mxGeometry x="100" y="{y_pos}" width="120" height="60" as="geometry"/>\n</mxCell>\n')
                y_pos += 80
            
            for j, e in enumerate(edges_raw):
                src = str(e["source"])
                tgt = str(e["target"])
                f.write(f'<mxCell id="edge_{j}" edge="1" parent="1" source="{src}" target="{tgt}">\n')
                f.write(f'  <mxGeometry relative="1" as="geometry"/>\n</mxCell>\n')
            
            f.write('</root></mxGraphModel></diagram></mxfile>\n')

    print(f"Successfully generated {fmt} static diagram at {file_path}")

def _export_langchain(modules_raw, file_path, fmt):   
    print(f"Generating {fmt} diagram via LangChain...")
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        print("Warning: GEMINI_API_KEY is not set. Cannot use LangChain model.")
        return
        
    llm = ChatGoogleGenerativeAI(
        model="gemini-2.5-flash", 
        temperature=0.1,
        google_api_key=api_key
        
    )
    
    module_text = ""
    for m in modules_raw:
        module_text += f"- **{m['name']}**: {m['summary']}\n"
        
    system_prompt = (
        f"You are an expert software architect. Create a valid {fmt} diagram representing the architecture "
        f"of the application based on the provided module descriptions. Include valid relationships "
        f"(e.g., depends on, contains). Output ONLY the raw {fmt} code, no Markdown blocks or explanations."
    )
    user_prompt = "Modules:\n{modules}"
    
    prompt = ChatPromptTemplate.from_messages([
        ("system", system_prompt),
        ("human", user_prompt)
    ])
    
    chain = prompt | llm | StrOutputParser()
    diagram_code = chain.invoke({"modules": module_text})
    
    
    diagram_code = diagram_code.replace("```mermaid\n", "").replace("```plantuml\n", "").replace("```xml\n", "").replace("```\n", "").replace("```", "")
    
    with open(file_path, "w") as f:
        f.write(diagram_code)
        
    print(f"Successfully generated {fmt} LangChain diagram at {file_path}")


def export_diagram(file_path="architecture.mermaid", fmt="mermaid", method="static"):
    """
    Generates a class diagram from the Nodes and Edges in Neo4j.
    Formats supported: mermaid, plantuml, drawio
    Methods: static, langchain
    """
    client = Neo4jClient()
    try:
        with client.session() as session:
            if method == "static":
                result_nodes = session.run("MATCH (n) WHERE 'Module' IN labels(n) OR 'File' IN labels(n) RETURN n.id AS id, n.name AS name, labels(n) AS labels")
                nodes_raw = [record.data() for record in result_nodes]
                
                
                result_edges = session.run("MATCH (a)-[r]->(b) WHERE ('Module' IN labels(a) OR 'File' IN labels(a)) AND ('Module' IN labels(b) OR 'File' IN labels(b)) RETURN a.id AS source, b.id AS target, type(r) AS type")
                edges_raw = [record.data() for record in result_edges]
                _export_static(nodes_raw, edges_raw, file_path, fmt)
            
            elif method == "langchain":
                result_modules = session.run("MATCH (m:Module) RETURN m.id AS id, m.name AS name, m.summary AS summary")
                modules = [record.data() for record in result_modules]
                if not modules:
                    print("No clustered Modules found. Cannot run Langchain generator. Run 'enrich' first.")
                    return
                _export_langchain(modules, file_path, fmt)
    finally:
        client.close()