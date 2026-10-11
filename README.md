# Impression d'étiquettes

## Lancer l'application

```sh
python3 label_app.py
```

Un autre dossier de CSV peut être fourni en argument :

```sh
python3 label_app.py /chemin/vers/les/csv
```

Les fichiers utilisent le séparateur `;`. Les lignes d'expéditeur sont
optionnelles et doivent précéder l'en-tête :

```csv
#EXPEDITEUR;SUD PTT 81 - 12 - 46 - 82
#EXPEDITEUR;59, rue Raymond Sommer - 81000 ALBI
#EXPEDITEUR;05 63 38 43 81 - sud81laposte@gmail.com
Destinataire;Adresse;Code postal;Ville
LA POSTE;Le Bourg;46500;ALVIGNAC
```

## Impression sur enveloppes

Le mode **Enveloppes** génère une page PDF par destinataire. Deux formats sont
disponibles :

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