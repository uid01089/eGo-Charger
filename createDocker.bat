pip freeze > requirements.txt
docker build -t egocharger -f Dockerfile .
docker tag egocharger:latest docker.diskstation/egocharger
docker push docker.diskstation/egocharger:latest