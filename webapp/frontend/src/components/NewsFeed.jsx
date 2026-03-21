// src/components/NewsFeed.jsx
import { useEffect, useState } from 'react'
import { getLatestNews } from '../utils/api'
import { ExternalLink, Newspaper } from 'lucide-react'

export default function NewsFeed() {
  const [articles, setArticles] = useState([])
  const [loading,  setLoading]  = useState(true)

  useEffect(() => {
    getLatestNews()
      .then(r => setArticles(r.data.articles || []))
      .catch(console.error)
      .finally(() => setLoading(false))
  }, [])

  if (loading) return (
    <div className="card animate-pulse h-48 flex items-center justify-center text-gray-600">
      Loading news...
    </div>
  )

  return (
    <div className="card">
      <div className="flex items-center gap-2 mb-3">
        <Newspaper size={14} className="text-gray-500" />
        <h2 className="text-sm font-semibold text-gray-300 uppercase tracking-wider">
          Market News
        </h2>
        <span className="text-xs text-gray-600 ml-auto">{articles.length} articles</span>
      </div>

      <div className="space-y-3 max-h-96 overflow-y-auto pr-1">
        {articles.length === 0 && (
          <p className="text-gray-600 text-sm text-center py-4">No news available</p>
        )}
        {articles.map((a, i) => (
          <div key={i} className="border-b border-gray-800/50 pb-3 last:border-0">
            <div className="flex items-start justify-between gap-2">
              <p className="text-xs text-gray-300 leading-relaxed flex-1">{a.title}</p>
              {a.url && (
                <a href={a.url} target="_blank" rel="noreferrer"
                  className="text-gray-600 hover:text-gray-400 flex-shrink-0 mt-0.5">
                  <ExternalLink size={11} />
                </a>
              )}
            </div>
            <div className="flex items-center gap-2 mt-1">
              <span className="text-gray-600 text-xs">{a.source_name}</span>
              {a.published_at && (
                <span className="text-gray-700 text-xs">
                  {new Date(a.published_at).toLocaleDateString()}
                </span>
              )}
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}
