from vivarium import Artifact
import sys
import pandas as pd

old_artifact = Artifact(sys.argv[1])
new_artifact = Artifact(sys.argv[2])

for key in old_artifact.keys:
    if key == "metadata.keyspace":
        continue
    data = old_artifact.load(key)
    if isinstance(data, pd.DataFrame) and 'draw_0' in data.columns and data['draw_0'].dtype == float:
        data['mean_draw'] = data.filter(like='draw_').mean(axis=1)
        data = data.drop(columns=data.filter(like='draw_').columns)
        data = data.rename(columns={'mean_draw': 'draw_0'})

    new_artifact.write(key, data)