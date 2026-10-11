// Erreurs communes à tous les backends de la couche d'accès aux données.

/** Erreur renvoyée par le serveur (4xx/5xx) avec un message lisible par l'humain. */
export class ApiError extends Error {
  constructor(message, status = 500, details = null) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.details = details;
  }
}

/**
 * Écriture refusée : le fichier a changé sur le disque depuis la révision connue de l'app (HTTP 409).
 * info = { doc: 'rig'|'anim', rev, author, at, changed_paths: string[] }
 */
export class ConflictError extends ApiError {
  constructor(info) {
    super('Conflit : le fichier a été modifié en dehors de l\'app.', 409);
    this.name = 'ConflictError';
    this.info = info;
  }
}
