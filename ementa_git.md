Ementa simples — Curso de Git

*Dia 1*

1. Introdução ao Git

Apresentação dos conceitos básicos de versionamento de código.

Pontos abordados:

O que é controle de versão
O que é Git
Repositório local e remoto
Working directory, staging area e repository
Fluxo básico de trabalho com Git

Momento de perguntas e respostas

2. Comandos base do Git

Comandos essenciais para uso no dia a dia.

Pontos abordados:

git init
git clone
git status
git add
git commit
git log
git diff
git push
git pull
git fetch

Também abordar:

Diferença entre git pull e git fetch
Como visualizar histórico de commits
Como consultar alterações antes do commit

Hands-on:
Criar um repositório local, adicionar arquivos, fazer commits e visualizar o histórico.

3. .gitignore e arquivos sensíveis

Ensinar como evitar que arquivos desnecessários ou sensíveis sejam versionados.

Pontos abordados:

O que é .gitignore
Quando usar .gitignore
Exemplos comuns:
node_modules/
.env
arquivos de build
arquivos temporários
Boas práticas para não subir arquivos sensíveis
O que fazer quando um arquivo sensível foi commitado por engano

Hands-on:
Criar um .gitignore, adicionar arquivos ignorados e validar com git status.

4. Autenticação com token de acesso

Explicar como autenticar no repositório remoto para realizar push.

Pontos abordados:

Por que senha não é mais o padrão
O que é um Personal Access Token
Como usar token para realizar push
Cuidados com segurança
Credential Manager
Boas práticas para armazenar credenciais

Hands-on:
Configurar um repositório remoto e realizar um git push autenticado.

5. VSCode com Git

Uso do Git integrado ao Visual Studio Code.

Pontos abordados:

Aba Source Control
Visualização de arquivos alterados
Stage e commit pelo VSCode
Comparação de mudanças
Push e pull pela interface
Histórico de alterações
Resolução simples de conflitos

Hands-on:
Alterar arquivos, fazer stage, commit e push usando o VSCode.

6. Commit Patterns

Boas práticas para mensagens de commit.

Pontos abordados:

Por que escrever bons commits
Commits pequenos e objetivos
Padrões de mensagem
Conventional Commits
Tipos comuns:
feat
fix
docs
style
refactor
test
chore

Exemplos:

feat: adiciona tela de login
fix: corrige validação do formulário
docs: atualiza instruções do README
refactor: reorganiza serviço de usuário

Hands-on:
Criar commits seguindo um padrão definido.


*Dia 2*

7. Branches e Feature Branch

Trabalho com branches para desenvolvimento isolado.

Pontos abordados:

O que é uma branch
Por que evitar trabalhar direto na main
Como criar branches
Como trocar de branch
Como fazer merge
Como deletar branches
Feature Branch
Boas práticas de branch naming

Exemplos de nomes de branches:

feature/login
feature/user-profile
fix/form-validation
hotfix/payment-error
docs/update-readme

Comandos:

git branch
git checkout
git switch
git merge
git branch -d

Hands-on:
Criar uma branch de feature, alterar arquivos, commitar e fazer merge na branch principal.

8. Git Flow

Apresentação de um fluxo mais estruturado para times.

Pontos abordados:

O que é Git Flow
Quando usar Git Flow
Branches principais:
main
develop
feature/*
release/*
hotfix/*
Diferença entre Git Flow e Feature Branch simples
Vantagens e cuidados ao usar Git Flow

Hands-on:
Simular um fluxo com develop, feature/login e merge de volta para develop.

9. Pull Request / Merge Request

Uso de PRs/MRs no fluxo de trabalho em equipe.

Pontos abordados:

O que é Pull Request
O que é Merge Request
Quando abrir um PR
Revisão de código
Comentários e sugestões
Aprovação
Merge
Boas práticas antes de abrir um PR

Checklist antes de abrir um PR:

Código funcionando
Commits organizados
Branch atualizada
Sem arquivos sensíveis
Sem alterações desnecessárias
Testes executados, quando existirem

Hands-on:
Criar uma branch, subir para o remoto e simular a abertura de um Pull Request.

10. Template de Pull Request

Ensinar como padronizar a abertura de PRs no projeto.

Pontos abordados:

O que é um template de PR
Por que usar template de PR
Como o template ajuda na revisão
Onde criar o arquivo de template
Campos comuns em um template

Exemplo de estrutura:

## Descrição

Explique brevemente o que foi feito neste PR.

## Tipo de alteração

- [ ] Nova funcionalidade
- [ ] Correção de bug
- [ ] Refatoração
- [ ] Documentação
- [ ] Ajuste de configuração

## Como testar

Descreva os passos para testar a alteração.

## Checklist

- [ ] Código revisado
- [ ] Testes executados
- [ ] Não foram adicionados arquivos sensíveis
- [ ] A branch está atualizada com a branch principal
- [ ] O PR possui título claro

Hands-on:
Criar um arquivo de template de PR no repositório e abrir um PR usando esse modelo.

11. Conflitos de merge

Ensinar como identificar e resolver conflitos.

Pontos abordados:

Por que conflitos acontecem
Como identificar conflitos
Como resolver conflitos no VSCode
Como finalizar o merge
Boas práticas para evitar conflitos frequentes

Hands-on:
Criar um conflito proposital em duas branches diferentes e resolver no VSCode.

12. Como desfazer alterações com segurança

Mostrar formas seguras de corrigir erros no Git.

Pontos abordados:

Desfazer alteração não commitada
Remover arquivo do stage
Corrigir último commit
Reverter commit
Diferença entre revert, reset e restore
Cuidados ao mexer no histórico

Comandos úteis:

git restore arquivo.txt
git restore --staged arquivo.txt
git commit --amend
git revert <hash-do-commit>
git reset

Hands-on:
Simular erros comuns e desfazer alterações com segurança.