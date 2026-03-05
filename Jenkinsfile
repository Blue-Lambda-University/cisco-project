pipeline {
    /* In this step, you can define where your job can run.
     * In more advanced usages, you can have the entire build be run inside of a Docker containers
     * in order to use custom tools not natively supported by Jenkins.
     */
    agent { node {label 'docker20X'} }
    //agent any
    /* The tools this pipeline needs are defined here. The available versions are the same as those
    * available in maven or freestyle job.
    */

    stages {
        /* In this stage, the code is being built/compiled, and the Docker image is being created and tagged.
         * Tests shouldn't been run in this stage, in order to speed up time to deployment.
         */
        stage ('Build') {
            steps {
                script{

                    if(!fileExists('google-cloud-sdk-279.0.0-linux-x86_64.tar.gz')){
                        sh 'curl -O https://dl.google.com/dl/cloudsdk/channels/rapid/downloads/google-cloud-sdk-279.0.0-linux-x86_64.tar.gz'
                    }
                    sh 'tar xzf google-cloud-sdk-279.0.0-linux-x86_64.tar.gz'
                    sh 'export CLOUDSDK_PYTHON="$(which python3)"'
                    GIT_COMMIT_HASH = sh (script: "git log -n 1 --pretty=format:'%H'", returnStdout: true)
                    GIT_TAG = sh(returnStdout: true, script: 'git tag --sort=-creatordate | head -n 1').trim()
                    if (!GIT_TAG?.trim()) {
                        echo "No tag found updating with git commit hash"
                        GIT_TAG = GIT_COMMIT_HASH
                    }
                    echo "Git tag:${GIT_TAG}"
                    //replace version with commit hash value in yaml before uploading
                    sh "grep -rl 'COMMIT_HASH' config | xargs sed -i 's/COMMIT_HASH/'${GIT_COMMIT_HASH}'/g'"
                    // update image tag with the git commit hash
                    //sh "grep -rl '_IMAGETAG' config | xargs sed -i 's/_IMAGETAG/'${GIT_COMMIT_HASH}'/g'"
                    //update git tag
                    sh "grep -rl 'GIT_TAG' config | xargs sed -i 's/GIT_TAG/'${GIT_TAG}'/g'"
                    // Run the docker build command and tag the image with the git commit ID

                    /*configFileProvider([configFile(fileId: '73a6a318-94d7-48b5-9465-40d6910bee10', variable: 'GOOGLE_APPLICATION_CREDENTIALS')]) {
                        sh "cat ${GOOGLE_APPLICATION_CREDENTIALS}  | docker login -u _json_key --password-stdin https://gcr.io"
                        sh "docker pull ${STAGE_IMAGE}"
                        //tag stage with prod tag
                        sh "docker tag ${STAGE_IMAGE} ${PROD_IMAGE}"
                    }*/

                    configFileProvider([configFile(fileId: '1d1cf282-cc92-4fd3-a74d-04fd3e0efecd', variable: 'GOOGLE_APPLICATION_CREDENTIALS')]) {
                        /*upload the yaml files*/
                        sh '"$(pwd)"/google-cloud-sdk/install.sh'
                        sh '"$(pwd)"/google-cloud-sdk/bin/gcloud auth activate-service-account  sa-global-jenkins-cicd@gcp-esearchspinnake-prd-50696.iam.gserviceaccount.com --key-file=${GOOGLE_APPLICATION_CREDENTIALS} --project=gcp-esearchspinnake-prd-50696'
                        sh '"$(pwd)"/google-cloud-sdk/bin/gsutil cp -r config/*.yaml gs://gs-global-platform-cicd-pipeline-artifacts/microsvc/cdcai/cdcai-microsvc-uber-assistant-frontend/'

                        /*GCR image push*/
                        sh "cat ${GOOGLE_APPLICATION_CREDENTIALS}  | docker login -u _json_key --password-stdin https://gcr.io"
                        //push prod tag
                        //sh "docker push ${PROD_IMAGE}"
                        docker.withRegistry('https://gcr.io/gcp-esearchspinnake-prd-50696') {
                           def customImage =  docker.build("gcp-esearchspinnake-prd-50696/gcr-global-platform-cicd-images/microsvc/cdcai/cdcai-microsvc-uber-assistant-frontend:${GIT_TAG}")
                           customImage.push()
                        }
                    }
                }
                //notifyDocker()
            }
        }
    }
    post {
        always {
            notifyBuildEnd()
        }
    }
}
