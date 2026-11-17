"""职业资讯与资讯知识库接口。"""
from flask import Blueprint, jsonify, request

from ..job_data import cache_json_response
from .career_news import get_career_news_payload
from .news_kb import get_kb_stats, search_news_kb


def create_blueprint():
    blueprint = Blueprint("news", __name__)

    @blueprint.route("/api/career-news")
    def api_career_news():
        force_refresh = str(request.args.get("refresh", "") or "").strip().lower() in {"1", "true", "yes"}
        payload = get_career_news_payload(force_refresh=force_refresh)
        return cache_json_response(payload, max_age=300)

    @blueprint.route("/api/news-kb/stats")
    def api_news_kb_stats():
        try:
            stats = get_kb_stats()
            return jsonify({"data": stats})
        except Exception as exc:
            return jsonify({"error": str(exc)}), 500

    @blueprint.route("/api/news-kb/search")
    def api_news_kb_search():
        query = str(request.args.get("q") or "").strip()
        if not query:
            return jsonify({"message": "请提供查询关键词 q"}), 400
        top_k = min(int(request.args.get("k") or 8), 20)
        try:
            results = search_news_kb(query, top_k=top_k)
            return jsonify({"data": results, "total": len(results)})
        except Exception as exc:
            return jsonify({"error": str(exc)}), 500

    return blueprint
