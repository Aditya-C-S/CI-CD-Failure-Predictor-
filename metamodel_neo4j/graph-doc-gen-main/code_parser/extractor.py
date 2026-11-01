import os
import pathspec
from tree_sitter import Language, Parser
import tree_sitter_python
import tree_sitter_java
import tree_sitter_cpp
try:
    from langchain_google_genai import GoogleGenerativeAIEmbeddings
    _GENAI_AVAILABLE = True
except ImportError:
    _GENAI_AVAILABLE = False

# Initialize languages
PY_LANGUAGE = Language(tree_sitter_python.language())
JAVA_LANGUAGE = Language(tree_sitter_java.language())
CPP_LANGUAGE = Language(tree_sitter_cpp.language())

# Expanded configuration mapping AST nodes for definitions and relations
LANG_CONFIGS = {
    ".py": {
        "lang": PY_LANGUAGE, 
        "class_node": "class_definition", 
        "func_node": "function_definition",
        "call_node": "call",
        "import_node": ["import_statement", "import_from_statement"]
    },
    ".java": {
        "lang": JAVA_LANGUAGE, 
        "class_node": "class_declaration", 
        "func_node": "method_declaration",
        "call_node": "method_invocation",
        "import_node": "import_declaration"
    },
    ".cpp": {
        "lang": CPP_LANGUAGE, 
        "class_node": "class_specifier", 
        "func_node": "function_definition",
        "call_node": "call_expression",
        "import_node": "preproc_include"
    },
    ".h": {
        "lang": CPP_LANGUAGE, 
        "class_node": "class_specifier", 
        "func_node": "function_definition",
        "call_node": "call_expression",
        "import_node": "preproc_include"
    },
}

class Extractor:
    def __init__(self, repo_id=None):
        self.repo_id = repo_id
        self.root_dir = None
        self.nodes = []
        self.edges = []
        self.parser = Parser()
        
        # Caching mechanisms for Multi-Pass parsing
        self.symbol_table = {}  # Maps symbol names to their Neo4j node IDs
        self.file_asts = []     # Caches ASTs to prevent re-parsing during Pass 2
        
        # Initialize Google GenAI Embeddings (optional – pipeline works without them)
        api_key = os.getenv("GEMINI_API_KEY")
        if _GENAI_AVAILABLE and api_key:
            self.embedder = GoogleGenerativeAIEmbeddings(model="models/gemini-embedding-001", google_api_key=api_key)
        else:
            self.embedder = None
            if not api_key:
                print("Info: GEMINI_API_KEY not set – node embeddings disabled (optional).")

    def _get_embedding(self, text):
        """Generates a mathematical vector for the node to support Continual Graph Learning."""
        if not self.embedder:
            return None
        try:
            return self.embedder.embed_query(text)
        except Exception as e:
            print(f"Warning: Failed to embed '{text}': {e}")
            return None

    def _get_rel_path(self, file_path):
        """Computes normalized relative path within the parsed repository root."""
        if self.root_dir:
            try:
                rel = os.path.relpath(file_path, self.root_dir).replace("\\", "/")
                if not rel.startswith("../") and not rel.startswith("..\\"):
                    return rel
            except Exception:
                pass
        return os.path.basename(file_path).replace("\\", "/")

    def parse_directory(self, root_dir, repo_id=None):
        """Executes the two-pass extraction pipeline with .gitignore support and repo_id scoping."""
        self.root_dir = os.path.abspath(root_dir)
        if repo_id:
            self.repo_id = repo_id
        if not self.repo_id:
            from maintenance.repo_utils import resolve_repo_id
            self.repo_id = resolve_repo_id(self.root_dir)
        
        # Load .gitignore if it exists in the root directory
        gitignore_path = os.path.join(root_dir, ".gitignore")
        ignore_spec = None
        if os.path.exists(gitignore_path):
            with open(gitignore_path, "r") as f:
                ignore_spec = pathspec.PathSpec.from_lines(
                    pathspec.patterns.GitWildMatchPattern, f
                )

        # PASS 1: Extract Hierarchy and Metadata
        for dirpath, dirnames, filenames in os.walk(root_dir):
            # Always ignore .git directory manually just in case
            if ".git" in dirpath:
                continue

            # Calculate relative directory path to apply pathspec accurately
            rel_dir = os.path.relpath(dirpath, root_dir)
            if rel_dir == ".":
                rel_dir = ""

            # Modifying dirnames IN-PLACE prunes the os.walk tree, 
            # preventing traversal into massive ignored directories (e.g., node_modules, venv)
            if ignore_spec:
                dirnames[:] = [
                    d for d in dirnames 
                    if not ignore_spec.match_file(os.path.join(rel_dir, d) + "/")
                ]

            for filename in filenames:
                file_path = os.path.join(dirpath, filename)
                rel_file_path = os.path.relpath(file_path, root_dir)

                # Skip if the file matches .gitignore patterns
                if ignore_spec and ignore_spec.match_file(rel_file_path):
                    continue

                ext = os.path.splitext(filename)[1]
                if ext in LANG_CONFIGS:
                    self._parse_file_pass1(file_path, ext, add_nodes=True)
        
        # PASS 2: Extract Relational Dependencies (CALLS, IMPORTS)
        self._execute_pass2()

    def _parse_file_pass1(self, file_path, ext, add_nodes=True):
        config = LANG_CONFIGS.get(ext)
        if not config:
            return

        parser = Parser(config["lang"])
        with open(file_path, "rb") as f:
            code = f.read()

        tree = parser.parse(code)
        
        # Add file node if requested
        rel_path = self._get_rel_path(file_path)
        repo_prefix = f"repo:{self.repo_id}:" if self.repo_id else ""
        file_id = f"{repo_prefix}file:{rel_path}" if self.repo_id else f"file:{file_path}"
        if add_nodes:
            file_embedding = self._get_embedding(f"File: {file_path}")
            props = {
                "id": file_id, 
                "path": file_path, 
                "file_path": file_path,
                "rel_path": rel_path,
                "name": os.path.basename(file_path),
                "embedding": file_embedding
            }
            if self.repo_id:
                props["repo_id"] = self.repo_id
            self.nodes.append({
                "type": "File",
                "properties": props
            })

        # Cache the tree for Pass 2
        self.file_asts.append({
            "tree": tree, "code": code, "config": config, "file_id": file_id, "file_path": file_path, "rel_path": rel_path
        })

        self._traverse_pass1(tree.root_node, code, config, file_id, file_path, rel_path, file_id, add_nodes=add_nodes)

    def _traverse_pass1(self, node, code, config, file_id, file_path, rel_path, parent_id, add_nodes=True):
        current_id = None
        repo_prefix = f"repo:{self.repo_id}:" if self.repo_id else ""
        
        if node.type == config["class_node"]:
            name_node = self._find_name_node(node)
            if name_node:
                name = code[name_node.start_byte:name_node.end_byte].decode("utf8")
                current_id = f"{repo_prefix}class:{rel_path}:{name}" if self.repo_id else f"class:{file_id}:{name}"
                
                self.symbol_table[name] = current_id
                
                if add_nodes:
                    # Extract signature/context for embedding
                    signature = f"Class {name} defined in {file_path}"
                    emb = self._get_embedding(signature)
                    
                    props = {
                        "id": current_id, 
                        "name": name, 
                        "file_path": file_path,
                        "rel_path": rel_path,
                        "start_line": node.start_point[0],
                        "end_line": node.end_point[0],
                        "embedding": emb
                    }
                    if self.repo_id:
                        props["repo_id"] = self.repo_id
                    self.nodes.append({
                        "type": "Class",
                        "properties": props
                    })
                    edge = {"from": parent_id, "to": current_id, "type": "CONTAINS"}
                    if self.repo_id:
                        edge["repo_id"] = self.repo_id
                    self.edges.append(edge)
                
        elif node.type == config["func_node"]:
            name_node = self._find_name_node(node)
            if name_node:
                name = code[name_node.start_byte:name_node.end_byte].decode("utf8")
                current_id = f"{repo_prefix}function:{rel_path}:{name}" if self.repo_id else f"function:{file_id}:{name}"
                
                self.symbol_table[name] = current_id
                
                if add_nodes:
                    # Extract signature/context for embedding
                    signature = f"Function {name} defined in {file_path}"
                    emb = self._get_embedding(signature)
                    
                    props = {
                        "id": current_id, 
                        "name": name, 
                        "file_path": file_path,
                        "rel_path": rel_path,
                        "start_line": node.start_point[0],
                        "end_line": node.end_point[0],
                        "embedding": emb
                    }
                    if self.repo_id:
                        props["repo_id"] = self.repo_id
                    self.nodes.append({
                        "type": "Function",
                        "properties": props
                    })
                    edge = {"from": parent_id, "to": current_id, "type": "CONTAINS"}
                    if self.repo_id:
                        edge["repo_id"] = self.repo_id
                    self.edges.append(edge)
        
        pass_parent_id = current_id if current_id else parent_id
        for child in node.children:
            self._traverse_pass1(child, code, config, file_id, file_path, rel_path, pass_parent_id, add_nodes=add_nodes)

    def _execute_pass2(self):
        """Iterates over cached ASTs to map relational edges."""
        for ast_data in self.file_asts:
            self._traverse_pass2(
                ast_data["tree"].root_node, 
                ast_data["code"], 
                ast_data["config"], 
                ast_data["file_id"], 
                ast_data.get("rel_path", ""),
                ast_data["file_id"]  # Initial context is the file scope
            )

    def _traverse_pass2(self, node, code, config, file_id, rel_path, current_context_id):
        repo_prefix = f"repo:{self.repo_id}:" if self.repo_id else ""
        new_context_id = current_context_id
        if node.type in [config["class_node"], config["func_node"]]:
            name_node = self._find_name_node(node)
            if name_node:
                name = code[name_node.start_byte:name_node.end_byte].decode("utf8")
                prefix = "class" if node.type == config["class_node"] else "function"
                new_context_id = f"{repo_prefix}{prefix}:{rel_path}:{name}" if self.repo_id else f"{prefix}:{file_id}:{name}"

        # Detect CALLS
        if node.type == config["call_node"]:
            called_name_node = self._get_call_identifier(node)
            if called_name_node:
                called_name = code[called_name_node.start_byte:called_name_node.end_byte].decode("utf8")
                # Resolve to known symbol if it exists in the graph
                target_id = self.symbol_table.get(called_name)
                if target_id and target_id != new_context_id:
                    edge = {"from": new_context_id, "to": target_id, "type": "CALLS"}
                    if self.repo_id:
                        edge["repo_id"] = self.repo_id
                    self.edges.append(edge)

        # Detect IMPORTS (Simplified mapping)
        import_rule = config.get("import_node")
        is_import = (node.type in import_rule) if isinstance(import_rule, (list, tuple, set)) else (node.type == import_rule)
        if is_import:
            external_id = f"{repo_prefix}module:ExternalModule" if self.repo_id else "ExternalModule"
            edge = {"from": file_id, "to": external_id, "type": "IMPORTS"}
            if self.repo_id:
                edge["repo_id"] = self.repo_id
            self.edges.append(edge)
            
        for child in node.children:
            self._traverse_pass2(child, code, config, file_id, rel_path, new_context_id)

    def _find_name_node(self, node):
        for child in node.children:
            if child.type == "identifier":
                return child
        return None

    def _get_call_identifier(self, node):
        """Extracts the identifier being invoked, handling properties/attributes."""
        for child in node.children:
            if child.type == "identifier":
                return child
            # Handle obj.method() or namespace::func()
            if child.type in ["attribute", "field_access", "scoped_identifier"]: 
                for sub in reversed(child.children):
                    if sub.type == "identifier":
                        return sub
        return None

    def get_graph(self):
        repo_prefix = f"repo:{self.repo_id}:" if self.repo_id else ""
        external_id = f"{repo_prefix}module:ExternalModule" if self.repo_id else "ExternalModule"
        # Guarantee the target node exists so Neo4j doesn't drop the IMPORTS edges
        if any(e["type"] == "IMPORTS" for e in self.edges):
            if not any(n["properties"].get("id") == external_id for n in self.nodes):
                props = {
                    "id": external_id,
                    "name": "External Dependencies",
                    "summary": "Third-party libraries and frameworks (e.g., Spring Boot, JPA)"
                }
                if self.repo_id:
                    props["repo_id"] = self.repo_id
                self.nodes.append({
                    "type": "Module",  # Treat it as a high-level module for the README
                    "properties": props
                })
                
        return {"nodes": self.nodes, "edges": self.edges}