# Application de gestion de stock — Librairie L'Espoir

Application web Flask + SQLite pour gérer le stock d'une librairie.

## Fonctionnalités

- Login administrateur
- Dashboard : total produits, marques, types, valeur du stock, alertes stock faible
- Consultation des produits
- Téléchargement PDF de la liste des produits
- Recherche par nom ou code-barres
- Filtrage par marque et type
- Ajout, modification et suppression de produit
- Gestion des marques
- Gestion des types de produits
- Code-barres obligatoire de 6 chiffres, unique
- Base de données SQLite créée automatiquement

## Identifiants par défaut

- Utilisateur : `admin`
- Mot de passe : `admin123`

## Lancement avec PowerShell + VS Code

1. Ouvrir le dossier dans VS Code.
2. Ouvrir le terminal PowerShell.
3. Exécuter :

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\run.ps1
```

4. Ouvrir dans le navigateur :

```text
http://127.0.0.1:5000
```

## Lancement manuel

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python app.py
```

## Structure

```text
librairie_espoir_stock/
├── app.py
├── requirements.txt
├── run.ps1
├── README.md
├── static/
│   └── style.css
└── templates/
    ├── base.html
    ├── login.html
    ├── dashboard.html
    ├── products.html
    ├── product_form.html
    ├── brands.html
    └── types.html
```
