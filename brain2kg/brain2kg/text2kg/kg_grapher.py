import networkx as nx
import matplotlib.pyplot as plt


class KGVisualizer:
    def __init__(self, triplets: list[list[list[str]]]):
        flattened_triplets = []
        for sentence_triplet in triplets:
            flattened_triplets.extend(sentence_triplet)
        self.triplets = flattened_triplets

    def graph_kg(self) -> None:
        G = nx.DiGraph()

        for subject, relation, object in self.triplets:
            G.add_edge(subject, object, label=relation)

        plt.figure(figsize=(20, 20))
        pos = nx.spring_layout(G, k=0.5, iterations=50)

        nx.draw(G, pos, with_labels=True, node_color='lightblue',
                node_size=1000, font_size=8, font_weight='bold')
        
        edge_labels = nx.get_edge_attributes(G, 'label')
        nx.draw_networkx_edge_labels(G, pos, edge_labels=edge_labels, font_size=6)

        plt.title('Generated KG Visualization', fontsize=16)

        plt.axis('off')
        plt.tight_layout()
        plt.show()