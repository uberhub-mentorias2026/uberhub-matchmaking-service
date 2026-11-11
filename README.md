# 🎯 Sistema de Matchmaking e Alocação de Mentores

## 📖 Sobre o Projeto
O **Sistema de Matchmaking** é um serviço dedicado a conectar mentores e mentorandos com base em múltiplos critérios (expertise, disponibilidade, idioma, formato e experiência). O sistema foi desenhado com um foco especial em resolver problemas de concorrência e consistência eventual na atualização de dados de busca, garantindo alocações seguras.

## 🏗️ Como Funciona (Pipeline de Decisão)
O processamento de candidatos e a alocação ocorrem nas seguintes etapas isoladas dentro do serviço:

1. **Pré-filtro**: Filtragem inicial no índice próprio por idioma e status ativo.
2. **Busca Híbrida**: Combinação de busca vetorial e palavras-chave (buscando de 3x a 5x mais candidatos que as vagas solicitadas para ter margem de segurança).
3. **Revalidação em Lote**: Consulta atômica à fonte da verdade para garantir que os candidatos ainda possuem vagas e descartar dados defasados do índice.
4. **Ranqueamento e Corte**: Filtro final dos candidatos válidos para entregar o Top N necessário.
5. **Explicação via LLM**: Geração opcional de justificativas do match para o Admin.

## 🔌 API e Endpoints

| Método | Endpoint | Descrição | 
| :--- | :--- | :--- | 
| `POST` | `/matchmaking` | Retorna o melhor mentor para uma necessidade. | 
| `POST` | `/matchmaking/batch` | Retorna uma lista ordenada com os Top N mentores. | 
| `POST` | `/matchmaking/score` | Calcula o score detalhado específico. | 
| `GET` | `/matchmaking/decisions/{id}` | Histórico e justificativas de decisões passadas. | 

## 📁 Estrutura de Documentação
Para detalhes arquiteturais aprofundados, algoritmos de scoring e decisões de engenharia, consulte a documentação na pasta `/docs`:

* [`/docs/matchmaking-one-pager.md`](docs/matchmaking-one-pager.md) - Visão geral da arquitetura e regras do algoritmo.
* [`/docs/adr/`](docs/adr/) - Registros de Decisão de Arquitetura (Architecture Decision Records).