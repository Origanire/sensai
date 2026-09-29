# Documentation Doxygen

Ce dossier contient tout le nécessaire pour générer la documentation technique
du projet avec [Doxygen](https://www.doxygen.nl).

## Prérequis

- Doxygen (1.9.8 ou plus récent) :

```bash
sudo apt-get install doxygen
doxygen --version
```

## Générer la documentation

Depuis **la racine du projet** :

```bash
doxygen doc/Doxyfile
```

La documentation HTML est générée dans `doc/html/`. Pour la consulter,
ouvre `doc/html/index.html` dans un navigateur.

## Régénérer proprement

```bash
rm -rf doc/html
doxygen doc/Doxyfile
```

## Contenu du dossier

| Élément | Rôle |
|---|---|
| `Doxyfile` | Configuration Doxygen du projet (versionné) |
| `html/` | Documentation générée (non versionnée, ignorée par git) |

## Conventions de documentation du code

La documentation est extraite des commentaires spéciaux `##` du code source :

- `## @file` en tête de chaque module (obligatoire : sans lui, Doxygen ignore
  les fonctions de niveau module) ;
- `## @brief`, `@param`, `@return`, `@exception` devant chaque fonction, classe
  ou attribut.

Exemple :

```python
## @brief Additionne deux nombres.
#
# @param a Premier nombre.
# @param b Second nombre.
# @return La somme.
def add(a, b):
    return a + b
```

> Astuce : un run de Doxygen doit se terminer **sans aucun warning**. Un
> warning « Member ... is not documented » signale un élément manquant dans la
> documentation générée.
