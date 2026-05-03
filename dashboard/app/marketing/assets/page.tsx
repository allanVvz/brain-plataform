"use client";
// Marketing/Assets reusa o mesmo componente que Knowledge/Assets para que a
// rota antiga (/knowledge/assets) e bookmarks externos continuem funcionando.
// Quando todas as rotas migrarem, este re-export some.
export { default } from "@/app/knowledge/assets/page";
