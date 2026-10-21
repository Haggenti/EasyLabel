# Impression d'étiquettes

## Lancer l'application

```sh
python3 label_app.py
```

Sous Windows, installer les dépendances puis lancer `launcher.bat` :

```bat
python -m pip install -r requirements.txt
launcher.bat
```

L'impression Windows utilise l'imprimante par défaut. Le choix de
l'imprimante reste disponible avec CUPS sous Linux.

Un autre dossier de CSV peut être fourni en argument :

```sh
python3 label_app.py /chemin/vers/les/csv
```

Les fichiers utilisent le séparateur `;`. Les lignes d'expéditeur sont
optionnelles et doivent précéder l'en-tête. La colonne `Adresse 2` est
optionnelle et permet de forcer une deuxième ligne d'adresse :

```csv
#EXPEDITEUR;SUD PTT 81 - 12 - 46 - 82
#EXPEDITEUR;59, rue Raymond Sommer - 81000 ALBI
#EXPEDITEUR;05 63 38 43 81 - sud81laposte@gmail.com
Destinataire;Adresse;Adresse 2;Code postal;Ville
LA POSTE;21 avenue du Test;Bâtiment A;46500;ALVIGNAC
```

## Impression sur enveloppes

Le mode **Enveloppes** génère une page PDF par destinataire. Des presets sont
disponibles et peuvent être créés, modifiés ou supprimés depuis **Mise en page >
Enveloppes > Gérer les formats...**. Deux presets sont fournis par défaut :

- DL : 220 x 110 mm ;
- C5 : 229 x 162 mm.

La position et la taille de la zone destinataire se règlent en millimètres.
Commencer par imprimer une enveloppe de test, puis ajuster X et Y selon le
chargement et les marges de l'imprimante.

En mode planche, `Colonne départ` et `Ligne départ` permettent de reprendre
une planche déjà commencée. Les positions sont comptées à partir de 1.

La case `Contours de calibration` ajoute des repères en pointillés dans le PDF
et l'aperçu. Elle permet de vérifier l'alignement sur une feuille ou une
enveloppe de test avant une impression réelle.

## Options d'impression

Chaque fichier CSV sélectionné peut avoir son propre nombre d'exemplaires.
Pour le modifier, faire un clic droit sur le fichier dans la liste puis
choisir **Nombre d'exemplaires...**. Le nombre par défaut est 1. Le nombre de
**Exemplaires globaux**, affiché en bas de la fenêtre, est un multiplicateur
appliqué à l'ensemble des fichiers sélectionnés. La liste affiche séparément
le nombre d'étiquettes et le nombre d'exemplaires de chaque fichier.

Le bouton **Imprimer** imprime systématiquement toutes les pages du PDF. Une
confirmation récapitule l'imprimante, le mode, le nombre global d'exemplaires
et l'ensemble des pages avant l'envoi. L'option
**Imprimer une page de test
avec les contours** imprime uniquement la première page avec les repères de
calibration.