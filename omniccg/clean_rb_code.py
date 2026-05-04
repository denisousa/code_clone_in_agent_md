import os
import re

class RubyBlackHoleSanitizer:
    def __init__(self, filepath):
        self.filepath = filepath
        with open(filepath, 'r', encoding='utf-8') as f:
            self.content = f.read()

    def sanitize_percent_arrays(self):
        """
        Converte %w|...| para ["..."]
        """
        def replace_words(match):
            content = match.group(1)
            words = content.split()
            return '[' + ', '.join([f'"{w}"' for w in words]) + ']'

        # Pega todos os delimitadores comuns: (), {}, [], ||
        self.content = re.sub(r'%w\s*[\|\{\[\(](.*?)[\|\} মৌসুম\)]', replace_words, self.content, flags=re.DOTALL)

    def sanitize_regex_literals(self):
        """
        Converte /regex/im para "REGEX_LITERAL".
        CORREÇÃO CRÍTICA: Agora consome os modificadores (i, m, x, o) após a barra final.
        """
        # Procura por regex literais comuns em Ruby (precedidos de (, =, space, match)
        # O grupo 2 ([a-z]*) captura o 'i', 'm', etc. e remove.
        
        # Caso 1: Argumento de função ou atribuição: (, /.../flags) ou = /.../flags
        self.content = re.sub(r'([(=,])\s*/([^/\n]+)/([a-z]*)', r'\1 "REGEX_LITERAL"', self.content)
        
        # Caso 2: match(/.../flags)
        self.content = re.sub(r'match\s*\(\s*/([^/\n]+)/([a-z]*)', r'match("REGEX_LITERAL"', self.content)
        
        # Caso 3: ~ /.../flags (match operator)
        self.content = re.sub(r'=~\s*/([^/\n]+)/([a-z]*)', r'=~ "REGEX_LITERAL"', self.content)

    def sanitize_reserved_keywords_methods(self):
        """
        Renomeia métodos que usam palavras reservadas.
        Ex: 'def for' quebra o parser. Vira 'def _for_safe'.
        """
        keywords = ['for', 'end', 'class', 'module', 'while', 'until', 'if', 'unless', 'case']
        
        for kw in keywords:
            # Substitui 'def kw' por 'def _kw_safe'
            # \b garante que não substitua 'def format' por 'def _for_safemat'
            pattern = fr'def\s+{kw}\b'
            replacement = f'def _{kw}_safe'
            self.content = re.sub(pattern, replacement, self.content)

    def sanitize_singleton_class(self):
        self.content = self.content.replace('class << self', 'class SelfSingleton')

    def sanitize_rspec_structure(self):
        """
        Simplifica a estrutura do RSpec para evitar 'Parse Time Limit Exceeded'.
        O NiCad entende 'def' muito melhor que blocos aninhados.
        
        Transforma:
            it "faz algo" do ... end
        Em:
            def it_faz_algo ... end
        """
        # 1. Remove strings de descrição do 'it' e transforma em nome de função
        def replacer(match):
            # match.group(1) é o tipo (it, context, describe)
            # match.group(2) é a string de descrição
            desc = match.group(2)
            # Limpa a descrição para virar um nome de variável válido
            clean_desc = re.sub(r'[^a-zA-Z0-9_]', '_', desc)
            return f"def {match.group(1)}_{clean_desc}"

        # Regex: procura (it|context|describe) "string" do
        pattern = r'\b(it|context|describe)\s+"([^"]+)"\s+do'
        self.content = re.sub(pattern, replacer, self.content)
        
        # 2. Remove chamadas complexas de 'should' e 'expect' que causam ruído
        # lambda { ... }.should raise_error -> apenas o bloco
        self.content = re.sub(r'lambda\s*\{', 'proc {', self.content) # lambda as vezes é keyword especial

    def sanitize_interpolation_and_symbols(self):
        # #{...} -> VAR
        self.content = re.sub(r'#\{.*?\}', 'VAR', self.content)
        
        # Corrige possíveis problemas de sintaxe de hash antiga/nova misturada que o regex deixou suja
        # : key => val (espaço extra causado por deleções anteriores)
        self.content = re.sub(r':\s+([a-zA-Z_]+)\s+=>', r':\1 =>', self.content)

    def save(self):
        with open(self.filepath, 'w', encoding='utf-8') as f:
            f.write(self.content)

def clean_file_rb(filepath):
    try:
        sanitizer = RubyBlackHoleSanitizer(filepath)
        
        # ORDEM DE EXECUÇÃO
        sanitizer.sanitize_percent_arrays()          # 1. Remove %w
        sanitizer.sanitize_regex_literals()          # 2. Remove /regex/flags (CORRIGIDO)
        sanitizer.sanitize_reserved_keywords_methods() # 3. Corrige 'def for' (CORRIGIDO)
        sanitizer.sanitize_singleton_class()         # 4. Corrige class << self
        sanitizer.sanitize_interpolation_and_symbols() # 5. Limpa strings
        sanitizer.sanitize_rspec_structure()         # 6. Achata o RSpec para evitar Timeout
        
        sanitizer.save()
        print(f"[OK] Cleaned: {filepath}")
        return True
    except Exception as e:
        print(f"[ERROR] Failed {filepath}: {e}")
        return False

def process_directory_rb(directory):
    count = 0
    errors = 0
    print(f"Starting BLACK HOLE RUBY cleaning in: {directory}")
    for root, _, files in os.walk(directory):
        for file in files:
            if file.endswith(".rb"):
                path = os.path.join(root, file)
                if clean_file_rb(path):
                    count += 1
                else:
                    errors += 1
    print(f"\nDone. Cleaned: {count}, Errors: {errors}")
