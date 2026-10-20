# Manuel de Tik

## Bienvenue dans Tik

Tik prépare et imprime des étiquettes et des enveloppes à partir de fichiers CSV.
Ce manuel explique les principales étapes, sans réglage technique inutile.

Le principe est toujours le même :

1. choisir les fichiers à imprimer ;
2. choisir **Planche d'étiquettes** ou **Enveloppes** ;
3. vérifier la mise en page ;
4. choisir l'imprimante et lancer l'impression.

## 1. Préparer les fichiers CSV

Tik utilise des fichiers CSV séparés par des points-virgules (`;`).

La première ligne doit contenir ces quatre colonnes :

```text
Destinataire;Adresse;Code postal;Ville
LA POSTE;Le Bourg;46500;ALVIGNAC
```

Les lignes d'expéditeur sont facultatives. Elles doivent être placées avant
l'en-tête et commencer par `#EXPEDITEUR` :

```text
#EXPEDITEUR;SUD PTT
#EXPEDITEUR;59, rue Raymond Sommer - 81000 ALBI
#EXPEDITEUR;05 63 38 43 81
Destinataire;Adresse;Code postal;Ville
```

Enregistrez le fichier en UTF-8. Un triangle d'avertissement signale qu'une
ligne du fichier doit être vérifiée.

## 2. Sélectionner les fichiers

La liste présente les fichiers CSV du dossier ouvert.

- cochez les fichiers à imprimer ;
- utilisez **Filtre** pour retrouver rapidement un fichier ;
- faites un clic droit sur un fichier pour modifier son nombre d'exemplaires ;
- utilisez **Exemplaires globaux** pour multiplier tous les fichiers sélectionnés.

Le résumé en bas de la fenêtre indique ce qui sera imprimé.

## 3. Préparer des étiquettes

Choisissez **Planche d'étiquettes** dans le menu **Mode**.

Dans **Gérer les formats**, choisissez un format existant ou créez-en un.
Vous pouvez régler :

- nombre de colonnes et de lignes ;
- marges et espaces entre les étiquettes ;
- position de départ sur une planche déjà commencée ;
- taille et position des textes ;
- rayon des coins pour les étiquettes arrondies ;
- police, taille, position et alignement des textes.

Pour vérifier l'alignement, utilisez **Imprimer une page de test** ou activez
les contours de calibration dans l'aperçu.

## 4. Préparer des enveloppes

Choisissez **Enveloppes** dans le menu **Mode**.

Les formats courants proposés sont :

- DL : 220 x 110 mm ;
- C5 : 229 x 162 mm.

Dans **Gérer les formats**, cliquez sur **Modifier la mise en page** pour régler :

- la largeur et la hauteur de l'enveloppe ;
- la position et la taille du destinataire ;
- la position de l'expéditeur ;
- les polices et l'alignement ;
- l'affichage du code postal dans des cases.

Utilisez **Imprimer une enveloppe test** avant une série complète. Si le texte
est décalé, corrigez sa position dans la mise en page.

## 5. Choisir l'imprimante et le papier

Cliquez sur **Imprimer**. Dans la fenêtre **Options d'impression** :

1. choisissez l'imprimante ;
2. choisissez le type de papier ;
3. choisissez la source du papier ;
4. cliquez sur **OK** pour confirmer.

Pour les enveloppes, la source **Multipurpose** est proposée par défaut lorsqu'elle existe sur l'imprimante.

Pour une enveloppe, vérifiez que le format choisi correspond à l'enveloppe
chargée : DL, C5 ou un autre format proposé par l'imprimante.

## 6. Vérifier ou exporter le résultat

- **Aperçu** permet de vérifier le résultat avant impression ;
- **Exporter le PDF** enregistre le document sans l'imprimer ;
- les contours de calibration servent à vérifier les marges et l'alignement.

## 7. Conserver les formats

Les formats peuvent être enregistrés, modifiés ou supprimés depuis
**Gérer les formats**.

Utilisez **Exporter les formats** pour conserver vos réglages ou les transférer
sur un autre ordinateur. Les formats d'étiquettes et d'enveloppes sont
exportés séparément.
