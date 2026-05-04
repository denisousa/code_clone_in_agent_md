import os
import ast
import sys

class SupernovaSanitizer(ast.NodeTransformer):
    """
    Sanitização extrema para NiCad/TXL.
    Remove Generics, DictComps, Decorators, Async, TypeHints e normaliza argumentos.
    """
    
    def visit_FunctionDef(self, node):
        node.returns = None
        node.decorator_list = [] # Remove decorators para evitar erros de indentação
        
        # Achatar argumentos (PosOnly, KwOnly -> Args normais)
        if hasattr(node.args, 'posonlyargs'):
            node.args.args = node.args.posonlyargs + node.args.args
            node.args.posonlyargs = []
            
        if node.args.kwonlyargs:
            node.args.args.extend(node.args.kwonlyargs)
            node.args.kwonlyargs = []
            node.args.kw_defaults = []

        for arg in node.args.args:
            arg.annotation = None
        if node.args.vararg: node.args.vararg.annotation = None
        if node.args.kwarg: node.args.kwarg.annotation = None

        self.generic_visit(node)
        return node

    def visit_AsyncFunctionDef(self, node):
        # Transforma async def em def normal
        new_node = ast.FunctionDef(
            name=node.name,
            args=node.args,
            body=node.body,
            decorator_list=[],
            lineno=node.lineno
        )
        return self.visit_FunctionDef(new_node)

    def visit_ClassDef(self, node):
        node.decorator_list = []
        node.keywords = [] # Remove keywords de classe (ex: metaclass=X)
        
        # CORREÇÃO DE GENERICS NA HERANÇA
        # class A(Generic[T]): -> class A(Generic):
        new_bases = []
        for base in node.bases:
            if isinstance(base, ast.Subscript):
                # Se a base for Generic[T], pega apenas o Generic (value)
                new_bases.append(base.value)
            else:
                new_bases.append(base)
        node.bases = new_bases
        
        self.generic_visit(node)
        return node

    def visit_arg(self, node):
        node.annotation = None
        return node

    def visit_AnnAssign(self, node):
        if node.value is None:
            return None
        return ast.Assign(targets=[node.target], value=node.value, lineno=node.lineno)

    def visit_Raise(self, node):
        node.cause = None # Remove 'from e'
        self.generic_visit(node)
        return node

    def visit_With(self, node):
        # Explode 'with A, B' em 'with A: with B:'
        if len(node.items) > 1:
            first_item = node.items[0]
            remaining_items = node.items[1:]
            nested_with = ast.With(items=remaining_items, body=node.body, lineno=node.lineno)
            node.items = [first_item]
            node.body = [nested_with]
            return self.visit(node)
        self.generic_visit(node)
        return node

    def visit_AsyncWith(self, node):
        new_node = ast.With(items=node.items, body=node.body, lineno=node.lineno)
        return self.visit(new_node)

    def visit_Await(self, node):
        return self.visit(node.value)

    def visit_AsyncFor(self, node):
        new_node = ast.For(
            target=node.target,
            iter=node.iter,
            body=node.body,
            orelse=node.orelse,
            lineno=node.lineno
        )
        self.generic_visit(new_node)
        return new_node

    def visit_Constant(self, node):
        # CORREÇÃO DE ELLIPSIS (...)
        if node.value is Ellipsis:
            return ast.Constant(value=None)
        return node
        
    def visit_Call(self, node):
        # CORREÇÃO DE ARGUMENTOS ESPECIAIS (__base__)
        # O parser falha em keywords começando com __
        for kw in node.keywords:
            if kw.arg and kw.arg.startswith("__"):
                kw.arg = kw.arg.replace("__", "") # __base__ -> base
        
        # Remove Unpacking no Call (func(*args, **kwargs))
        # Transforma em argumentos posicionais simples para manter o fluxo
        new_args = []
        for arg in node.args:
            if isinstance(arg, ast.Starred):
                new_args.append(arg.value)
            else:
                new_args.append(arg)
        node.args = new_args
        
        # Remove Unpacking de Keywords (**kwargs)
        # Transforma o valor do kwargs em um argumento posicional extra
        new_keywords = []
        for kw in node.keywords:
            if kw.arg is None: # É um **kwargs
                node.args.append(kw.value)
            else:
                new_keywords.append(kw)
        node.keywords = new_keywords

        self.generic_visit(node)
        return node

    def visit_DictComp(self, node):
        # CORREÇÃO DE DICT COMPREHENSION
        # {k:v for k,v in x} -> [(k,v) for k,v in x] (ListComp)
        # O TXL entende ListComp, mas não DictComp
        
        # Cria uma tupla (k, v)
        elt = ast.Tuple(elts=[node.key, node.value], ctx=ast.Load())
        
        new_node = ast.ListComp(
            elt=elt,
            generators=node.generators
        )
        self.generic_visit(new_node)
        return new_node

    def visit_Set(self, node):
        # {a, b} -> [a, b]
        return ast.List(elts=[self.visit(e) for e in node.elts], ctx=ast.Load())

    def visit_SetComp(self, node):
        # {x for x in y} -> [x for x in y]
        return ast.ListComp(elt=self.visit(node.elt), generators=node.generators)

    def visit_Dict(self, node):
        new_keys = []
        new_values = []
        for k, v in zip(node.keys, node.values):
            if k is None: # **unpacking
                new_keys.append(ast.Constant(value="UNPACKED"))
                new_values.append(v)
            else:
                new_keys.append(k)
                new_values.append(v)
        node.keys = new_keys
        node.values = new_values
        self.generic_visit(node)
        return node

    def visit_Starred(self, node):
        # [*args] -> [args]
        return self.visit(node.value)

    def visit_Match(self, node):
        combined_body = []
        for case in node.cases:
            combined_body.extend(case.body)
        if not combined_body: combined_body = [ast.Pass()]
        
        new_node = ast.If(
            test=ast.Constant(value=True),
            body=combined_body,
            orelse=[],
            lineno=node.lineno
        )
        self.generic_visit(new_node)
        return new_node

    def visit_NamedExpr(self, node):
        # (x := y) -> y
        return self.visit(node.value)

def clean_file(filepath):
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            source = f.read()
        
        try:
            tree = ast.parse(source)
        except SyntaxError as e:
            print(f"[SKIP] SyntaxError nativo: {filepath} - {e}")
            return False
        
        sanitizer = SupernovaSanitizer()
        tree = sanitizer.visit(tree)
        ast.fix_missing_locations(tree)
        
        clean_source = ast.unparse(tree)
        
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(clean_source)
            
        return True
    except Exception as e:
        print(f"[ERROR] Failed {filepath}: {e}")
        return False

def process_directory_py(directory):
    count = 0
    errors = 0
    print(f"Starting SUPERNOVA cleaning in: {directory}")
    for root, _, files in os.walk(directory):
        for file in files:
            if file.endswith(".py"):
                path = os.path.join(root, file)
                if clean_file(path):
                    count += 1
                else:
                    errors += 1
    print(f"\nDone. Cleaned: {count}, Errors: {errors}")
