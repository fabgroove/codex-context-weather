#!/usr/bin/env python3
"""Create an inline snapshot from native token metadata; no hook state writes."""
import argparse
import json
from pathlib import Path
from context_weather import codex_home, measure, read_settings, valid_session


def create_fragment(session, transcript, label, output, home):
    if not valid_session(session) or not label or len(label) > 120:
        raise ValueError('Invalid source identity')
    sample = measure(transcript, session, home)['sample']
    if sample is None or not isinstance(sample.get('timestamp'), str):
        raise ValueError('No reliable native measurement')
    settings = read_settings(home)
    data = dict(label=label, percent=sample['percent'], tokens=sample['tokens'],
                window=sample['window'], timestamp=sample['timestamp'],
                threshold=settings['threshold_percent'], language=settings['language'],
                refresh_prompts={
                    'fr':f"Actualise en lecture seule la mesure native de contexte du chat {session} ({label}) et affiche sa jauge intégrée sous ta réponse. Ne relance pas ce chat, ne lui envoie pas de message et ne modifie ni son état d’alerte ni ses fichiers. La mesure doit rester datée ; aucune estimation, compaction ou création de chat.",
                    'en':f"Refresh the native context measurement for chat {session} ({label}) in read-only mode and show its dated inline gauge below your reply. Do not resume or message the measured chat, change alert state or project files, compact, or create a chat. Do not estimate the value. Respond in English."
                },
                handoff_prompts={
                    'fr':f"Je demande de poursuivre le chat source {session} ({label}) dans une seule nouvelle discussion du même projet. Applique le skill contexte-reprise-projet. Au prochain point sûr, prépare une synthèse privée autonome de la conversation : objectif, décisions et corrections, autorisations et interdictions, résultats réellement vérifiés et preuves utiles, travail restant, prochaine action, agents/sessions/verrous et opérations en cours, résultats inconnus, automatisations et leur rattachement. N'inclus ni secret ni conversation brute. Vérifie le projet et l'hôte du chat source avec les outils natifs puis list_projects ; vérifie qu'aucun relais n'est déjà créé ou en vol. Crée ensuite une seule discussion locale dans ce même projet via create_thread, avec la synthèse complète dans son premier message et les références locales nécessaires, sans recopier tout l'historique. N'ouvre pas de worktree. Conserve le chat source et toutes ses automatisations à leur emplacement ; ne les déplace pas et ne les duplique pas ; conserve le chat source sauf si je demande explicitement son archivage. Ne déclenche pas de compaction du chat source pour cette action. Le nouveau chat doit d'abord confirmer la bonne reprise, sans reprendre les travaux métier ni écrire dans le projet avant une nouvelle demande. Vérifie sa réception et fournis son lien natif. Si le projet ne peut être établi ou si le résultat de création est inconnu, arrête la création et réconcilie l'état sans second essai automatique.",
                    'en':f"I request one new chat to continue source chat {session} ({label}) in the same project. Use the contexte-reprise-projet skill. At a safe stopping point prepare a private, self-contained summary: objective, decisions and corrections, authorization boundaries, verified results and evidence, remaining work and next step, active agents/sessions/locks, unknown outcomes, and automation ownership. Exclude secrets and raw conversation history. Verify the source project and host with native tools and list_projects; check that no handoff already exists or is in flight. Use create_thread once to create a local chat in that same project with the complete summary in its first message and necessary local references. Do not create a worktree, compact the source, or move/duplicate its automations. Keep the source chat unless I explicitly request its archival. The new chat must first confirm receipt and continuity without continuing business work or writing project files until a new request. Verify receipt and return the native chat link. If project identity or creation outcome is unknown, stop and reconcile without automatic retry. Respond in English."
                })
    encoded = json.dumps(data, ensure_ascii=False).replace('<', '\\u003c').replace('\u2028', '\\u2028').replace('\u2029', '\\u2029')
    template = Path(__file__).with_suffix('.html').read_text()
    assert template.count('@@SAMPLE@@') == 1
    fragment = template.replace('@@SAMPLE@@', encoded)
    if output.is_symlink():
        raise ValueError('Refused symlink output')
    with output.open('x', encoding='utf-8') as f:
        f.write(fragment)
    assert output.read_text() == fragment
    return {'status':'created_readback_verified','percent':round(sample['percent'],2),
            'measured_at':sample['timestamp'],'output':str(output),'live_polling':False}


if __name__ == '__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--session',required=True)
    p.add_argument('--transcript',required=True)
    p.add_argument('--label',required=True)
    p.add_argument('--output',required=True,type=Path)
    a=p.parse_args()
    print(json.dumps(create_fragment(a.session,a.transcript,a.label,a.output,codex_home()),ensure_ascii=False))
