"""Keep chart labels searchable without indexing vector drawing coordinates."""
import json
import re


def searchable_text(text):
    def labels(match):
        try:
            chart = json.loads(match.group(1))
            def walk(node, depth=0):
                if depth > 40 or not isinstance(node, dict): return []
                result = [str(node.get('text') or '')] if node.get('tag') in ('text', 'tspan') else []
                for child in node.get('children', [])[:1500]: result.extend(walk(child, depth+1))
                return result
            return '[图表快照] ' + ' '.join(walk(chart.get('tree', {})))
        except (ValueError, TypeError, AttributeError):
            return '[图表快照]'
    return re.sub(r'^```stellar-chart\s*\n(.*?)\n```\s*$', labels, text, flags=re.M | re.S)
