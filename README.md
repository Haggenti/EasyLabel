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