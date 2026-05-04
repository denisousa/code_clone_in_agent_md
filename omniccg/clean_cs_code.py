import os
import re

class CSharpNuclearSanitizer:
    def __init__(self, filepath):
        self.filepath = filepath
        with open(filepath, 'r', encoding='utf-8') as f:
            self.content = f.read()

    def remove_preprocessor_directives(self):
        """
        Remove linhas começando com # (ex: #if, #region, #nullable).
        Isso resolve o problema de fechar chaves depois de um #endif.
        """
        # Remove a linha inteira, mas mantém a quebra de linha para não alterar contagem de linhas drasticamente
        self.content = re.sub(r'^\s*#.*$', '', self.content, flags=re.MULTILINE)

    def convert_filescoped_namespace(self):
        """
        Converte 'namespace X;' para 'namespace X { ... }'.
        Como já removemos os #directives, podemos adicionar o } no final sem medo.
        """
        # Regex para encontrar namespace file-scoped
        pattern = r'^(?P<indent>\s*)namespace\s+(?P<name>[\w\.]+)\s*;'
        match = re.search(pattern, self.content, re.MULTILINE)
        
        if match:
            # Substitui por 'namespace X {'
            self.content = re.sub(pattern, f"{match.group('indent')}namespace {match.group('name')} {{", self.content, count=1, flags=re.MULTILINE)
            # Adiciona o fecha chaves no final do arquivo
            if not self.content.endswith('\n'):
                self.content += '\n'
            self.content += '}\n'
            return True
        return False

    def remove_modern_modifiers(self):
        """
        Remove modificadores que confundem parsers antigos ou não existiam em contextos específicos.
        Lista: public, private, protected, internal, sealed, override, virtual, readonly, static abstract
        """
        # Remove 'static abstract' (C# 11) especificamente primeiro
        self.content = re.sub(r'\bstatic\s+abstract\s+', '', self.content)
        
        # Remove modificadores de acesso comuns. 
        # Para clone detection, saber se é public ou private importa pouco, a estrutura do método importa mais.
        modifiers = [
            'public', 'private', 'protected', 'internal', 
            'sealed', 'override', 'virtual', 'readonly', 'async' # async também pode ser removido para simplificar
        ]
        
        # Cria regex (ex: \bpublic\s+)
        pattern = r'\b(' + '|'.join(modifiers) + r')\s+'
        self.content = re.sub(pattern, '', self.content)

    def clean_generics(self):
        """
        Remove 'in' e 'out' de definições genéricas. 
        Ex: interface I<out T> -> interface I<T>
        """
        # Isso é um pouco bruto, remove 'out ' e 'in ' se estiverem precedidos de '<' ou ','
        # Exemplo simplificado para pegar casos comuns
        self.content = re.sub(r'(<|,)\s*(out|in)\s+', r'\1 ', self.content)

    def remove_nullables(self):
        """
        Remove '?' de tipos anuláveis.
        Ex: string? -> string
        """
        # Remove ? se estiver logo após uma palavra (tipo) e não for um operador ternário (espaço depois)
        # Regex: palavra seguida de ?
        self.content = re.sub(r'(?<=\w)\?', '', self.content)

    def remove_attributes(self):
        """
        Tenta remover atributos [Key], [Required], etc.
        Isso é difícil de fazer perfeito com regex, mas removemos os casos simples de linha única.
        """
        self.content = re.sub(r'^\s*\[.+\]\s*$', '', self.content, flags=re.MULTILINE)

    def save(self):
        with open(self.filepath, 'w', encoding='utf-8') as f:
            f.write(self.content)

def clean_file_cs(filepath):
    try:
        sanitizer = CSharpNuclearSanitizer(filepath)
        
        # A ORDEM IMPORTA
        sanitizer.remove_preprocessor_directives() # 1. Remove #if para não atrapalhar o namespace
        sanitizer.remove_attributes()              # 2. Remove atributos
        sanitizer.convert_filescoped_namespace()   # 3. Arruma namespace
        sanitizer.remove_modern_modifiers()        # 4. Remove static abstract, public, etc
        sanitizer.clean_generics()                 # 5. Limpa <out T>
        sanitizer.remove_nullables()               # 6. Remove string?
        
        sanitizer.save()
        return True
    except Exception as e:
        return False

def process_directory_cs(directory):
    count = 0
    errors = 0
    print(f"Starting NUCLEAR C# cleaning in: {directory}")
    for root, _, files in os.walk(directory):
        for file in files:
            if file.endswith(".cs"):
                path = os.path.join(root, file)
                if clean_file_cs(path):
                    count += 1
                else:
                    errors += 1
    print(f"\nDone. Cleaned: {count}, Errors: {errors}")
