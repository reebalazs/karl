' runs test1.html against IE
'saves results as results_ie_staging_eurasia_suite.html

echo " runs test1.html against IE"
echo "saves results as results_ie_staging_eurasia_suite.html"

java -jar "selenium-server-1.0.1\selenium-server.jar" -htmlSuite "*iexplore" "http://staging.eurasia.sixfeetup.com/" "../staging_suite.html" "../log/results_ie_staging_eurasia_suite.html"

