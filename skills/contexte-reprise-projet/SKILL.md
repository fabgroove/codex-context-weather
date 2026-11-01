---
name: contexte-reprise-projet
description: Alerte et synthèse de reprise quand une mesure native de contexte atteint le seuil choisi, ou sur demande de passage de relais. Préserver le projet, les opérations et les automatisations en cours.
---

# Météo du contexte et reprise

Ce skill accompagne les hooks du paquet Codex Context Weather. Le seuil se règle dans `$CODEX_HOME/context-weather.json` (par défaut `~/.codex/context-weather.json`) : `threshold_percent` entre 1 et 99, 60 par défaut. `action` peut valoir `notify`, `prepare`, `compact`, `new-chat` ou `compact-and-new-chat`. `language` choisit les alertes françaises (`fr`, défaut) ou anglaises (`en`). Le panneau propose aussi un sélecteur FR/EN local à sa visite. Lire ce seul réglage avant la reprise ; ne pas modifier la configuration ou les hooks sans demande.

## Alerte visible

Le hook produit un avertissement natif dans Codex et un contexte additionnel au prochain appel d'outil ou nouveau message après une mesure dépassant le seuil. Il ne surveille pas les chats inactifs et ne fonctionne qu'après l'approbation native des hooks. Il n'ajoute aucun panneau à l'interface de Codex.

Répondre brièvement à l'alerte en indiquant le pourcentage mesuré et la prochaine étape. Aucune estimation fondée sur la longueur des messages, le cumul de tokens de la session ou les limites d'abonnement. Une mesure manquante reste inconnue. L'adaptateur de métadonnées est borné et dépend du format natif des journaux ; un changement de format peut le rendre indisponible. Ne pas contourner cette limite par une base interne ou un export de conversations.

Le hook déduplique par chat, fenêtre de compaction et réglage. Un seuil ou une action nouvellement choisis peuvent provoquer une nouvelle alerte. Ne pas réinitialiser l'état pour faire réapparaître une alerte réelle ; utiliser des données fictives pour un test.

## Jauge sous la réponse

L'utilisateur demande l'affichage dans la discussion, sous le dernier message, sans panneau latéral par défaut. À réception d'une alerte, lire intégralement le skill `visualize` disponible puis afficher un petit fragment intégré dans la réponse finale. Utiliser le générateur installé `scripts/inline_weather.py --session ID --transcript CHEMIN_NATIF --label NOM --output CHEMIN_AUTORISÉ.html`. Vérifier l'identité du chat source transmise par le hook ; obtenir son chemin et son titre uniquement par les métadonnées natives en lecture seule, sans reprendre un autre chat. Pour le chat courant, utiliser son dernier compteur, jamais celui d'un autre projet par proximité.

Le générateur n'écrit aucun état d'alerte et refuse un compteur absent ou un fichier de sortie existant. Choisir une sortie privée, durable et explicitement accessible en écriture au chat. Il produit une mesure datée, une jauge compacte, le seuil, FR/EN et un bouton d'actualisation sur demande. Le fragment intégré n'accède à aucune API, aucun réseau ni service local : sa valeur ne se met pas à jour toute seule. Ne jamais le présenter comme un compteur en direct. Le bouton demande une nouvelle lecture au chat qui contient la jauge ; il ne relance pas le chat mesuré. Suivre le contrat de rendu `visualize` et inclure sa référence dans la réponse finale seulement. Sur une surface sans rendu intégré, fournir le texte daté et annoncer cette limite ; ne pas prétendre avoir affiché une jauge.

Les actions et les langues sont alignées à gauche, sous la mesure, en laissant la zone supérieure droite libre pour les contrôles natifs. « Nouveau chat avec résumé » transmet une demande de relais au chat ; ce clic ne crée rien directement dans le fragment. Lorsqu'une telle demande est effectivement reçue de l'utilisateur, préparer la synthèse puis créer un seul nouveau chat local dans le même projet vérifié avec `list_projects` et `create_thread`, sans worktree ni compaction préalable. Le premier message contient la synthèse autonome et ses références ; demander au nouveau chat seulement de confirmer la reprise, puis vérifier sa réception avec `wait_threads`. L'ancien chat et ses automatisations restent en place. Conserver le reçu de création et l'identité du relais dans le checkpoint privé autorisé du projet pour éviter une seconde création. Un résultat inconnu exige une réconciliation par les outils natifs, sans rejeu. Annoncer le lien natif après vérification ; ne jamais appeler `handoff_thread`, qui déplace un checkout et ne remplace pas ce passage de contexte. Les autres actions au seuil conservent leurs règles propres.

Un panneau séparé reste une option explicite de l'utilisateur, distincte de la jauge sous la réponse. Ne pas confondre réception par l'assistant, message système visible, rendu intégré présenté et affichage confirmé par l'utilisateur. Une alerte ne donne aucun droit supplémentaire de compaction ou de création de chat.

## Préparer la reprise

Au prochain point sûr, consulter les AGENTS/README et la seule fiche canonique du projet. Préparer une synthèse autonome et courte : objectif ; décisions et corrections ; autorisations et limites ; dernier résultat prouvé et références ; travail restant et prochaine action ; opérations en vol, agents, verrous et résultats inconnus ; automatisations rattachées au chat lorsqu'elles concernent la reprise.

Ne pas interrompre une écriture ou un agent, rejouer un résultat inconnu, ni démarrer un second rédacteur. Ne pas inclure de secret, corps de mail ou conversation brute. Le résumé reste privé dans le projet ou dans le message de relais. Si une fiche canonique est actualisée, suivre sa procédure d'archive et de relecture ; la synthèse ne la remplace pas.

## Actions au seuil

- `notify` : avertir seulement.
- `prepare` : préparer la synthèse sans changer de chat.
- `compact` : préparer la synthèse, puis utiliser une fonction native de compaction lorsqu'elle est réellement disponible et autorisée. Sinon indiquer la commande native `/compact` à l'utilisateur ; ne pas simuler de saisie ni annoncer une compaction non exécutée.
- `new-chat` : après préparation, créer une seule discussion dans le même projet vérifié si l'utilisateur a demandé ce relais et si l'outil natif est disponible. Transmettre la synthèse dans le premier message, avec les références utiles.
- `compact-and-new-chat` : conserver la synthèse avant la compaction ; vérifier la compaction si elle est disponible, puis créer la nouvelle discussion avec cette synthèse. Si une étape native manque, annoncer précisément cette limite et fournir le relais prêt à copier. Ne pas traiter la configuration seule comme une nouvelle autorisation métier ou un droit universel de créer des chats.

Une demande de synthèse seule ne demande pas un nouveau chat. Une demande explicite de relais au seuil vaut pour le périmètre désigné par l'utilisateur : ne pas redemander la même autorisation. Avant toute création, vérifier l'identifiant du projet, l'hôte et l'absence de création en vol pour cette reprise. Garder le chat source et ses automatisations ; ne pas les déplacer, archiver ou dupliquer implicitement. Si le résultat d'une création est inconnu, réconcilier avec l'outil natif avant tout nouvel essai. Annoncer séparément synthèse préparée, compaction vérifiée et discussion créée avec son lien natif.

## Test et distribution

L'installation du skill n'est pas une preuve d'activation des hooks. Les tests fictifs du seuil ne prouvent pas une notification rendue. Distinguer tests, installation, approbation native et affichage observé. Pour une distribution, ne joindre que le paquet source et ses exemples fictifs ; exclure réglages personnels, états, journaux, sauvegardes privées et résumés. Ne publier sur GitHub que sur demande explicite.

## Présentation et choix du relais

Afficher FR/EN en texte plus petit, sans cadre coloré : la langue sélectionnée apparaît en bleu. Conserver les autres boutons inchangés. Proposer le choix facultatif d’archiver le chat source après confirmation de réception, décoché par défaut. Le clic de création demande automatiquement un unique relais ; si un contrôle de sécurité le bloque, rapporter le refus et demander la confirmation ou intervention exigée, sans contourner le contrôle. Une demande d’archivage concerne le chat source seul, jamais ses automatisations.
